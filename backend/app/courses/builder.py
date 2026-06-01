"""ChapterTreeBuilder — parse PDF outline + LLM-driven KP segmentation.

Produces a 4-layer tree (Course → Chapter → Section → KnowledgePoint) by:
  1. extracting the PDF table-of-contents (first two outline levels only)
  2. for each Section, asking the LLM to slice 3–7 KnowledgePoints
  3. validating LLM output against a strict pydantic schema, retrying once
  4. persisting the tree atomically and flipping Course.generation_status
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import fitz  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, ValidationError

from sqlalchemy import select

from app.config import settings
from app.courses.embedding import index_course_chunks
from app.db import SessionLocal
from app.kp.prewarm import prewarm_kp_materials
from app.llm import complete_json
from app.user_llm import load_api_settings
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    Section,
)

logger = logging.getLogger(__name__)

# ---------- LLM IO schema ----------

KP_SYSTEM_PROMPT = """你是教学助理。把给定章节内容切分为 1-3 个知识点。
一个知识点 = 一个能坐下来学 10-20 分钟的完整话题，而不是一个孤立的小概念。
宁可合并，不要碎切：只有当本章节明显包含多个互相独立的主题、或篇幅明显过长时，
才拆成多个；短章节或单一主题的章节，只产出 1 个知识点。
知识点之间互不重叠，按学习顺序排列。
严格输出 JSON，遵循该 schema：
{
  "knowledge_points": [
    {
      "title": "知识点标题（中文，简短，不超过 30 字）",
      "page_start": 12,
      "page_end": 14,
      "description": "1-2 句中文说明该知识点要学什么"
    }
  ]
}
约束：
- knowledge_points 数组长度必须 >= 1 且 <= 3
- 每个知识点的 page_start/page_end 必须落在给定章节的页码范围内
- title 必须为中文，不能为空
"""


class _KPSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    page_start: int = Field(..., ge=1)
    page_end: int = Field(..., ge=1)
    description: str | None = Field(None, max_length=500)


class _KPListSchema(BaseModel):
    knowledge_points: list[_KPSchema] = Field(..., min_length=1, max_length=3)


# Sections shorter than this collapse to a single KP synthesized from the
# section itself (title = section title, whole-section page range) with no
# LLM call — a short / single-topic section should not be split. Tunable.
SHORT_SECTION_CHARS = 1500


SKELETON_SYSTEM_PROMPT = """你是教学助理。给定一份 PDF 的逐页文本摘要（每页前若干字 + 页码），推断这份资料合理的两层章节骨架。
严格输出 JSON，遵循该 schema：
{
  "chapters": [
    {
      "title": "章标题（中文，简短，不超过 50 字）",
      "sections": [
        {"title": "节标题（中文，简短）", "page_start": 1, "page_end": 5}
      ]
    }
  ]
}
约束：
- chapters 数组长度 1-24；每个 chapter 的 sections 长度 1-10
- 所有 page_start / page_end 必须落在 1..N 范围内（N = 总页数，会在用户消息中给出）
- page_start <= page_end；同一 chapter 内 sections 按 page_start 递增；尽量覆盖整本资料
- 标题用中文，概括内容，不要照抄页码或页眉
"""


class _SectionSkeletonSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    page_start: int = Field(..., ge=1)
    page_end: int = Field(..., ge=1)


class _ChapterSkeletonSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    sections: list[_SectionSkeletonSchema] = Field(..., min_length=1, max_length=10)


class _SkeletonSchema(BaseModel):
    chapters: list[_ChapterSkeletonSchema] = Field(..., min_length=1, max_length=24)


# ---------- PDF parsing ----------


@dataclass
class SectionLayout:
    title: str
    page_start: int  # 1-based, inclusive
    page_end: int    # 1-based, inclusive


@dataclass
class ChapterLayout:
    title: str
    sections: list[SectionLayout]


def _parse_toc_layout(toc: list[list], total_pages: int) -> list[ChapterLayout]:
    entries = [(int(lvl), str(title), int(page)) for lvl, title, page in toc if int(lvl) <= 2]
    chapters: list[ChapterLayout] = []
    current_chapter: ChapterLayout | None = None
    for i, (lvl, title, page) in enumerate(entries):
        next_page = entries[i + 1][2] if i + 1 < len(entries) else total_pages + 1
        end_page = max(page, next_page - 1)
        if lvl == 1:
            current_chapter = ChapterLayout(title=title.strip(), sections=[])
            chapters.append(current_chapter)
        else:  # lvl == 2
            if current_chapter is None:
                continue
            current_chapter.sections.append(
                SectionLayout(title=title.strip(), page_start=page, page_end=end_page)
            )
    return [c for c in chapters if c.sections]


# Front/back matter title cues. A chapter counts as matter only inside the
# leading or trailing contiguous run of the chapter list — never an interior
# chapter — so a body chapter literally titled "引言"/"导言" is not stripped
# unless it actually sits at the very front before any body content.
_FRONT_MATTER_TERMS = (
    "序言", "序章", "前言", "引言", "导言", "卷首语", "致读者", "序",
)
_BACK_MATTER_TERMS = (
    "结语", "结束语", "后记", "编后记", "跋", "附录", "致谢",
    "参考文献", "参考书目", "索引", "术语表", "版权页",
)


def _matches_matter(title: str, terms: tuple[str, ...]) -> bool:
    t = title.strip()
    return any(t == term or t.startswith(term) for term in terms)


def partition_matter(
    chapters: list[ChapterLayout],
) -> tuple[list[ChapterLayout], list[ChapterLayout], list[ChapterLayout]]:
    """Split a chapter list into (body, front_matter, back_matter).

    Only the leading contiguous run matching a front-matter cue and the
    trailing contiguous run matching a back-matter cue are peeled off;
    interior chapters are always body. No-match → (chapters, [], []).
    """
    n = len(chapters)
    i = 0
    while i < n and _matches_matter(chapters[i].title, _FRONT_MATTER_TERMS):
        i += 1
    j = n
    while j > i and _matches_matter(chapters[j - 1].title, _BACK_MATTER_TERMS):
        j -= 1
    return chapters[i:j], chapters[:i], chapters[j:]


def _summarize_pages_for_skeleton(
    page_texts: list[str],
    *,
    per_page_chars: int = 200,
    max_total_chars: int = 60_000,
) -> str:
    parts: list[str] = []
    used = 0
    for idx, text in enumerate(page_texts, start=1):
        snippet = " ".join(text.split())[:per_page_chars]
        line = f"P{idx}: {snippet}"
        if used + len(line) > max_total_chars:
            break
        parts.append(line)
        used += len(line) + 1
    return "\n".join(parts)


async def _infer_skeleton_via_llm(
    page_texts: list[str],
    *,
    total_pages: int,
    api_settings: dict | None = None,
    max_retries: int = 1,
) -> list[ChapterLayout]:
    """LLM-driven fallback when the PDF has no usable outline.

    Asks the LLM to propose a two-level Chapter/Section skeleton with page ranges,
    then validates the output against ``_SkeletonSchema`` and the page bounds.
    Retries once on invalid output, mirroring ``extract_kps_for_section``.
    """
    summary = _summarize_pages_for_skeleton(page_texts)
    user_msg = f"总页数：{total_pages}\n\n逐页摘要：\n{summary}"
    messages = [
        {"role": "system", "content": SKELETON_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = await complete_json(api_settings, messages)
            data = json.loads(raw)
            parsed = _SkeletonSchema.model_validate(data)
            chapters: list[ChapterLayout] = []
            for ch in parsed.chapters:
                sections: list[SectionLayout] = []
                for sec in ch.sections:
                    if sec.page_start > sec.page_end:
                        raise ValueError(
                            f"节「{sec.title}」页码反向：{sec.page_start}-{sec.page_end}"
                        )
                    if sec.page_start < 1 or sec.page_end > total_pages:
                        raise ValueError(
                            f"节「{sec.title}」页码 {sec.page_start}-{sec.page_end} "
                            f"超出 PDF 范围 1-{total_pages}"
                        )
                    sections.append(
                        SectionLayout(
                            title=sec.title.strip(),
                            page_start=sec.page_start,
                            page_end=sec.page_end,
                        )
                    )
                chapters.append(
                    ChapterLayout(title=ch.title.strip(), sections=sections)
                )
            return chapters
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_err = exc
            logger.warning(
                "LLM skeleton inference failed (attempt %s/%s): %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )
            continue
    raise ValueError(f"LLM 推断章节骨架失败：{last_err}")


async def _extract_pdf(
    pdf_path: str, *, api_settings: dict | None = None
) -> tuple[list[ChapterLayout], list[str]]:
    doc = fitz.open(pdf_path)
    try:
        toc = doc.get_toc()
        page_texts = [page.get_text() for page in doc]
        total_pages = doc.page_count
    finally:
        doc.close()

    layout: list[ChapterLayout] = []
    if toc:
        layout = _parse_toc_layout(toc, total_pages=total_pages)
    if not layout:
        logger.info("PDF 无可用目录，调用 LLM 推断章节骨架")
        layout = await _infer_skeleton_via_llm(
            page_texts, total_pages=total_pages, api_settings=api_settings
        )
    if not layout:
        raise ValueError("无法从 PDF 推断出可用的章节骨架")
    return layout, page_texts


def _section_text(page_texts: list[str], section: SectionLayout, max_chars: int = 12000) -> str:
    joined = "\n".join(page_texts[section.page_start - 1 : section.page_end])
    return joined[:max_chars]


# ---------- LLM call ----------


async def extract_kps_for_section(
    section: SectionLayout,
    section_text: str,
    *,
    api_settings: dict | None = None,
    max_retries: int = 1,
) -> list[_KPSchema]:
    """Call LLM in JSON mode to slice a section into KPs. Validates + retries once."""
    user_msg = (
        f"章节标题：{section.title}\n"
        f"页码范围：{section.page_start} - {section.page_end}\n\n"
        f"章节内容：\n{section_text}"
    )
    messages = [
        {"role": "system", "content": KP_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = await complete_json(api_settings, messages)
            data = json.loads(raw)
            parsed = _KPListSchema.model_validate(data)
            for kp in parsed.knowledge_points:
                if kp.page_start > kp.page_end:
                    raise ValueError(
                        f"KP「{kp.title}」页码反向：{kp.page_start}-{kp.page_end}"
                    )
                if not (
                    section.page_start <= kp.page_start
                    and kp.page_end <= section.page_end
                ):
                    raise ValueError(
                        f"KP「{kp.title}」页码 {kp.page_start}-{kp.page_end} "
                        f"超出章节范围 {section.page_start}-{section.page_end}"
                    )
            return parsed.knowledge_points
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_err = exc
            logger.warning(
                "LLM KP extraction failed for section %r (attempt %s/%s): %s",
                section.title,
                attempt + 1,
                max_retries + 1,
                exc,
            )
            continue
    raise ValueError(f"LLM 输出不合规：{last_err}")


# ---------- Orchestration ----------


@dataclass
class KPPayload:
    title: str
    page_start: int
    page_end: int
    description: str | None
    # Set only for the synthetic 全书导读/全书总结 KPs (kind="overview"
    # /"summary"). `matter_pages` carries the front/back-matter page
    # ranges fed to the book-level material generator. Normal KPs leave
    # both None and use page_start/page_end as usual.
    kind: str | None = None
    matter_pages: list[tuple[int, int]] | None = None


@dataclass
class SectionPayload:
    title: str
    knowledge_points: list[KPPayload]


@dataclass
class ChapterPayload:
    title: str
    sections: list[SectionPayload]


OVERVIEW_TITLE = "全书导读"
SUMMARY_TITLE = "全书总结"


def _matter_page_ranges(matter: list[ChapterLayout]) -> list[tuple[int, int]]:
    return [(s.page_start, s.page_end) for ch in matter for s in ch.sections]


def _synthetic_matter_chapter(
    title: str, kind: str, matter_pages: list[tuple[int, int]]
) -> ChapterPayload:
    """A single-KP chapter that brackets the body (总-分-总). The KP has
    no page range so chat uses semantic retrieval over the whole book;
    `matter_pages` feeds the book-level material generator."""
    kp = KPPayload(
        title=title,
        page_start=0,
        page_end=0,
        description=None,
        kind=kind,
        matter_pages=matter_pages,
    )
    return ChapterPayload(
        title=title,
        sections=[SectionPayload(title=title, knowledge_points=[kp])],
    )


def _kp_boundary(kp: KPPayload) -> dict:
    """Persisted KP boundary. Synthetic overview/summary KPs carry a
    `kind` marker + matter page ranges and *no* page_start/page_end, so
    chat falls back to whole-book semantic retrieval for them."""
    if kp.kind is not None:
        return {
            "kind": kp.kind,
            "matter_pages": [list(pr) for pr in (kp.matter_pages or [])],
        }
    return {
        "page_start": kp.page_start,
        "page_end": kp.page_end,
        "description": kp.description,
    }


MD_VIRTUAL_PAGE_CHARS = 1500


def _extract_md(md_path: str) -> tuple[list[str], int]:
    """Read a Markdown file and split into virtual pages of ~1500 chars.

    Markdown has no native page concept; we synthesize "pages" so the
    LLM-skeleton path (already used by outline-less PDFs) can produce
    meaningful page_start/page_end ranges.
    """
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        raise ValueError("Markdown 文件为空")
    page_texts: list[str] = []
    for i in range(0, len(text), MD_VIRTUAL_PAGE_CHARS):
        page_texts.append(text[i : i + MD_VIRTUAL_PAGE_CHARS])
    return page_texts, len(page_texts)


async def compute_chapter_tree(
    source_path: str,
    *,
    api_settings: dict | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[ChapterPayload]:
    """Pure compute: PDF / Markdown → list of ChapterPayload. No DB writes.

    KP extraction across sections runs concurrently (issue 17), bounded by
    `kp_extraction_concurrency` to respect DeepSeek rate limits. A single
    section failing aborts the whole build (failures aggregate via
    `gather(return_exceptions=True)`); we surface the first error in a
    composite ValueError so the caller writes a meaningful generation_error.

    `on_progress(done, total)` (issue 20) is invoked once with (0, total)
    after the layout is parsed, then once per completed Section. Exceptions
    in the callback are swallowed so progress reporting never breaks the
    build.
    """
    lower = source_path.lower()
    if lower.endswith(".md") or lower.endswith(".markdown"):
        page_texts, total_pages = _extract_md(source_path)
        layout = await _infer_skeleton_via_llm(
            page_texts, total_pages=total_pages, api_settings=api_settings
        )
        if not layout:
            raise ValueError("无法从 Markdown 推断出可用的章节骨架")
    else:
        layout, page_texts = await _extract_pdf(
            source_path, api_settings=api_settings
        )

    # Front/back matter never becomes body KPs — it feeds the synthetic
    # 全书导读/全书总结 KPs that bracket the body (总-分-总).
    layout, front_matter, back_matter = partition_matter(layout)

    sema = asyncio.Semaphore(settings.kp_extraction_concurrency)
    flat_sections: list[tuple[int, int, SectionLayout]] = [
        (ci, si, sec)
        for ci, ch in enumerate(layout)
        for si, sec in enumerate(ch.sections)
    ]
    total = len(flat_sections)
    done = 0
    done_lock = asyncio.Lock()

    async def _safe_progress(d: int, t: int) -> None:
        if on_progress is None:
            return
        try:
            await on_progress(d, t)
        except Exception:  # noqa: BLE001
            logger.exception("on_progress callback failed")

    await _safe_progress(0, total)

    async def _extract_one(sec: SectionLayout) -> list[_KPSchema]:
        nonlocal done
        text = _section_text(page_texts, sec)
        if len(text) < SHORT_SECTION_CHARS:
            # Short / single-topic section → one KP, no LLM call.
            result = [
                _KPSchema(
                    title=sec.title[:200] or "知识点",
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    description=None,
                )
            ]
        else:
            async with sema:
                result = await extract_kps_for_section(
                    sec, text, api_settings=api_settings
                )
        async with done_lock:
            done += 1
            current = done
        await _safe_progress(current, total)
        return result

    results = await asyncio.gather(
        *(_extract_one(sec) for _, _, sec in flat_sections),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        raise ValueError(
            f"{len(failures)}/{len(results)} 个 Section 切分失败；首个错误：{failures[0]}"
        )

    chapters: list[ChapterPayload] = [
        ChapterPayload(title=ch.title, sections=[]) for ch in layout
    ]
    for (ci, _si, sec), kp_models in zip(flat_sections, results, strict=True):
        kp_payloads = [
            KPPayload(
                title=kp.title,
                page_start=kp.page_start,
                page_end=kp.page_end,
                description=kp.description,
            )
            for kp in kp_models  # type: ignore[union-attr]
        ]
        chapters[ci].sections.append(
            SectionPayload(title=sec.title, knowledge_points=kp_payloads)
        )

    if chapters:
        chapters = [
            _synthetic_matter_chapter(
                OVERVIEW_TITLE, "overview", _matter_page_ranges(front_matter)
            ),
            *chapters,
            _synthetic_matter_chapter(
                SUMMARY_TITLE, "summary", _matter_page_ranges(back_matter)
            ),
        ]
    return chapters


async def build_chapter_tree(course_id: uuid.UUID, pdf_path: str) -> None:
    """Build a course's chapter tree end-to-end. Owns its own DB session."""
    async with SessionLocal() as db:
        course = await db.get(Course, course_id)
        if course is None:
            logger.warning("build_chapter_tree: course %s not found", course_id)
            return
        course.generation_status = GenerationStatus.running
        course.generation_error = None
        course.progress_done = 0
        course.progress_total = 0
        await db.commit()
        # Resolve once as a plain dict — the configured BYO keys are used
        # for skeleton/KP-extraction LLM calls and PDF embedding.
        api_settings = await load_api_settings(db)

        async def _on_progress(d: int, t: int) -> None:
            # Use a fresh session so progress writes don't interleave with
            # the main build transaction. Issue 20.
            async with SessionLocal() as pdb:
                c = await pdb.get(Course, course_id)
                if c is not None:
                    c.progress_done = d
                    c.progress_total = t
                    await pdb.commit()

        try:
            chapters = await compute_chapter_tree(
                pdf_path, api_settings=api_settings, on_progress=_on_progress
            )
            for ch_idx, ch in enumerate(chapters):
                chapter_obj = Chapter(
                    course_id=course_id, title=ch.title, order_index=ch_idx
                )
                db.add(chapter_obj)
                await db.flush()
                for sec_idx, sec in enumerate(ch.sections):
                    section_obj = Section(
                        chapter_id=chapter_obj.id,
                        title=sec.title,
                        order_index=sec_idx,
                    )
                    db.add(section_obj)
                    await db.flush()
                    for kp_idx, kp in enumerate(sec.knowledge_points):
                        db.add(
                            KnowledgePoint(
                                section_id=section_obj.id,
                                title=kp.title,
                                order_index=kp_idx,
                                boundary=_kp_boundary(kp),
                            )
                        )
            course.generation_status = GenerationStatus.done
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("build_chapter_tree failed for course %s", course_id)
            await db.rollback()
            failed = await db.get(Course, course_id)
            if failed is not None:
                failed.generation_status = GenerationStatus.failed
                failed.generation_error = str(exc)[:1000]
                await db.commit()
            raise

    # Index PDF for RAG retrieval after chapter tree is committed. Failure here
    # is non-fatal — chat still works on KP-boundary text without retrieval.
    # Markdown sources are not indexed (embedding pipeline is fitz-only); chat
    # falls back to KP-boundary text via the same retrieval-disabled path.
    if not pdf_path.lower().endswith((".md", ".markdown")):
        try:
            n = await index_course_chunks(api_settings, course_id, pdf_path)
            logger.info("indexed %s chunks for course %s", n, course_id)
        except Exception:  # noqa: BLE001
            logger.exception("index_course_chunks failed for course %s", course_id)

    # Spawn per-KP material generation in the background (see app.kp.prewarm).
    # Chat dialogue (Layer 3 checklist/keyphrases) and the assessor both
    # depend on KPMaterial existing — by spawning here, they're warm by the
    # time the student opens a KP. Exercise sets are NOT generated here —
    # they're tailored after the assessor produces covered_concepts.
    # Fire-and-forget: builder returns once the chapter tree commits;
    # prewarm runs to completion independently.
    asyncio.create_task(prewarm_kp_materials(course_id))
