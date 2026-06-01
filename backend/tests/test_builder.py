import json
import re
import uuid
from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest
from sqlalchemy import delete, select

from app.courses import builder
from app.db import SessionLocal
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    Section,
)


def _fill_page(page, i: int, label: str = "lorem ipsum dolor sit amet consectetur") -> None:
    """Fill a page with enough text that any multi-page section exceeds
    builder.SHORT_SECTION_CHARS, so it goes through the LLM extraction path
    rather than the short-section fast-path."""
    y = 56
    for j in range(45):
        page.insert_text((40, y), f"Page {i + 1} line {j}: {label}.")
        y += 16


def _make_fixture_pdf(tmp_path: Path) -> Path:
    """Build a PDF with a 2-level outline and long page text (LLM path)."""
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page()
        _fill_page(page, i)
    toc = [
        [1, "Chapter 1", 1],
        [2, "Section 1.1", 1],
        [2, "Section 1.2", 4],
        [1, "Chapter 2", 7],
        [2, "Section 2.1", 7],
        [2, "Section 2.2", 10],
    ]
    doc.set_toc(toc)
    out = tmp_path / "fixture.pdf"
    doc.save(str(out))
    doc.close()
    return out


def _make_fixture_pdf_no_outline(tmp_path: Path) -> Path:
    """Build a PDF with no outline (LLM-skeleton fallback runs) + long pages."""
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page()
        _fill_page(page, i)
    out = tmp_path / "fixture_no_outline.pdf"
    doc.save(str(out))
    doc.close()
    return out


def _is_skeleton_call(messages: list[dict]) -> bool:
    return "推断这份资料合理的两层章节骨架" in messages[0]["content"]


def _stub_kp_response(page_start: int, page_end: int, count: int = 3) -> str:
    return json.dumps(
        {
            "knowledge_points": [
                {
                    "title": f"知识点 {i + 1}",
                    "page_start": page_start,
                    "page_end": page_end,
                    "description": f"描述 {i + 1}",
                }
                for i in range(count)
            ]
        },
        ensure_ascii=False,
    )


def test_parse_toc_layout_groups_two_levels_and_assigns_page_ranges():
    toc = [
        [1, "Chapter 1", 1],
        [2, "Section 1.1", 1],
        [3, "deep level — should be ignored", 2],
        [2, "Section 1.2", 5],
        [1, "Chapter 2", 8],
        [2, "Section 2.1", 8],
    ]
    layout = builder._parse_toc_layout(toc, total_pages=10)
    assert [c.title for c in layout] == ["Chapter 1", "Chapter 2"]
    assert [s.title for s in layout[0].sections] == ["Section 1.1", "Section 1.2"]
    s11, s12 = layout[0].sections
    assert (s11.page_start, s11.page_end) == (1, 4)   # next entry at page 5
    assert (s12.page_start, s12.page_end) == (5, 7)   # next chapter at page 8
    s21 = layout[1].sections[0]
    assert (s21.page_start, s21.page_end) == (8, 10)  # last entry → total_pages


def test_parse_toc_layout_drops_chapters_without_sections():
    toc = [
        [1, "Lonely chapter", 1],
        [1, "Real chapter", 4],
        [2, "Section A", 4],
    ]
    layout = builder._parse_toc_layout(toc, total_pages=8)
    assert len(layout) == 1
    assert layout[0].title == "Real chapter"


def _ch(title: str, ps: int, pe: int) -> "builder.ChapterLayout":
    return builder.ChapterLayout(
        title=title,
        sections=[builder.SectionLayout(title=title, page_start=ps, page_end=pe)],
    )


def test_partition_matter_splits_leading_and_trailing_matter():
    chapters = [
        _ch("序言", 1, 2),
        _ch("第一章 绪论", 3, 6),
        _ch("第二章 方法", 7, 10),
        _ch("附录", 11, 12),
    ]
    body, front, back = builder.partition_matter(chapters)
    assert [c.title for c in body] == ["第一章 绪论", "第二章 方法"]
    assert [c.title for c in front] == ["序言"]
    assert [c.title for c in back] == ["附录"]


def test_partition_matter_keeps_interior_matter_looking_chapter():
    # "引言" sits *after* a body chapter → it is real content, not front
    # matter, and must stay in body.
    chapters = [
        _ch("第一章 背景", 1, 4),
        _ch("引言", 5, 6),
        _ch("第三章 结论", 7, 10),
    ]
    body, front, back = builder.partition_matter(chapters)
    assert [c.title for c in body] == ["第一章 背景", "引言", "第三章 结论"]
    assert front == [] and back == []


async def test_extract_kps_validates_and_retries_once_on_bad_output(monkeypatch):
    section = builder.SectionLayout(title="t", page_start=1, page_end=5)
    calls = {"n": 0}

    async def stub(_api, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            # Too many KPs (4 > 3) → should fail validation and retry
            return _stub_kp_response(1, 5, count=4)
        return _stub_kp_response(1, 5, count=2)

    monkeypatch.setattr(builder, "complete_json", stub)
    kps = await builder.extract_kps_for_section(section, "...", api_settings={})
    assert calls["n"] == 2
    assert 1 <= len(kps) <= 3
    assert len(kps) == 2
    assert all(kp.page_start == 1 and kp.page_end == 5 for kp in kps)


async def test_extract_kps_raises_after_retry_exhausted(monkeypatch):
    section = builder.SectionLayout(title="t", page_start=1, page_end=5)

    async def stub(_api, _messages):
        return "this is not json"

    monkeypatch.setattr(builder, "complete_json", stub)
    with pytest.raises(ValueError, match="LLM 输出不合规"):
        await builder.extract_kps_for_section(section, "...", api_settings={})


async def test_extract_kps_rejects_pages_out_of_section_range(monkeypatch):
    section = builder.SectionLayout(title="t", page_start=10, page_end=15)
    calls = {"n": 0}

    async def stub(_api, _messages):
        calls["n"] += 1
        # Always return KP with page outside section's range
        return _stub_kp_response(1, 5, count=3)

    monkeypatch.setattr(builder, "complete_json", stub)
    with pytest.raises(ValueError, match="超出章节范围"):
        await builder.extract_kps_for_section(section, "...", api_settings={})
    assert calls["n"] == 2  # initial + 1 retry


async def test_extract_kps_rejects_too_many(monkeypatch):
    """New cap: >3 KPs is invalid (was <=7). Always returning 4 → raises."""
    section = builder.SectionLayout(title="t", page_start=1, page_end=5)

    async def stub(_api, _messages):
        return _stub_kp_response(1, 5, count=4)

    monkeypatch.setattr(builder, "complete_json", stub)
    with pytest.raises(ValueError, match="LLM 输出不合规"):
        await builder.extract_kps_for_section(section, "...", api_settings={})


async def test_compute_chapter_tree_end_to_end(tmp_path, monkeypatch):
    pdf_path = _make_fixture_pdf(tmp_path)

    async def stub(_api, messages):
        user_msg = messages[-1]["content"]
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        assert m, f"unexpected user prompt: {user_msg!r}"
        ps, pe = int(m.group(1)), int(m.group(2))
        return _stub_kp_response(ps, pe, count=3)

    monkeypatch.setattr(builder, "complete_json", stub)

    tree = await builder.compute_chapter_tree(str(pdf_path), api_settings={})

    # Body is bracketed by synthetic 全书导读/全书总结 (总-分-总).
    assert tree[0].title == builder.OVERVIEW_TITLE
    assert tree[-1].title == builder.SUMMARY_TITLE
    body = tree[1:-1]
    # 4-layer structure: course (implicit) → 2 chapters → sections → KPs
    assert len(body) == 2
    assert all(len(ch.sections) == 2 for ch in body)
    for ch in body:
        for sec in ch.sections:
            assert 1 <= len(sec.knowledge_points) <= 3
            for kp in sec.knowledge_points:
                assert kp.title.strip()
                assert kp.page_start >= 1
                assert kp.page_end >= kp.page_start
                assert kp.description is not None
                assert kp.kind is None  # body KPs are not synthetic


def _make_fixture_pdf_short(tmp_path: Path) -> Path:
    """Same TOC as _make_fixture_pdf but tiny page text, so every section is
    under SHORT_SECTION_CHARS and takes the fast-path (no LLM call)."""
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page()
        page.insert_text((50, 72), f"Page {i + 1}: short.")
    toc = [
        [1, "Chapter 1", 1],
        [2, "Section 1.1", 1],
        [2, "Section 1.2", 4],
        [1, "Chapter 2", 7],
        [2, "Section 2.1", 7],
        [2, "Section 2.2", 10],
    ]
    doc.set_toc(toc)
    out = tmp_path / "fixture_short.pdf"
    doc.save(str(out))
    doc.close()
    return out


async def test_compute_chapter_tree_short_sections_use_fast_path(tmp_path, monkeypatch):
    """Short sections collapse to one KP synthesized from the section title,
    with no LLM call at all (the stub raises if reached)."""
    pdf_path = _make_fixture_pdf_short(tmp_path)

    async def stub(_api, _messages):
        raise AssertionError("LLM must not be called for short sections")

    monkeypatch.setattr(builder, "complete_json", stub)

    tree = await builder.compute_chapter_tree(str(pdf_path), api_settings={})

    body = tree[1:-1]  # strip synthetic 全书导读/全书总结
    assert len(body) == 2
    assert all(len(ch.sections) == 2 for ch in body)
    for ch in body:
        for sec in ch.sections:
            assert len(sec.knowledge_points) == 1  # fast-path: one KP
            kp = sec.knowledge_points[0]
            assert kp.title == sec.title
            assert kp.page_start >= 1
            assert kp.page_end >= kp.page_start
            assert kp.kind is None


def _make_fixture_pdf_with_matter(tmp_path: Path) -> Path:
    """PDF whose TOC has 序言 (front) and 附录 (back) as level-1 chapters,
    each with a level-2 section so they survive `_parse_toc_layout`."""
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page()
        _fill_page(page, i, "body text for testing")
    toc = [
        [1, "序言", 1],
        [2, "序言", 1],
        [1, "第一章 基础", 3],
        [2, "1.1 概念", 3],
        [2, "1.2 应用", 5],
        [1, "第二章 进阶", 7],
        [2, "2.1 深化", 7],
        [1, "附录", 11],
        [2, "附录 A", 11],
    ]
    doc.set_toc(toc)
    out = tmp_path / "fixture_matter.pdf"
    doc.save(str(out))
    doc.close()
    return out


async def test_compute_chapter_tree_brackets_body_with_overview_and_summary(
    tmp_path, monkeypatch
):
    pdf_path = _make_fixture_pdf_with_matter(tmp_path)
    seen_sections: list[str] = []

    async def stub(_api, messages):
        user_msg = messages[-1]["content"]
        m = re.search(r"章节标题：(.+)", user_msg)
        assert m, f"unexpected KP-extraction prompt: {user_msg!r}"
        seen_sections.append(m.group(1).strip())
        pr = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        return _stub_kp_response(int(pr.group(1)), int(pr.group(2)), count=3)

    monkeypatch.setattr(builder, "complete_json", stub)

    tree = await builder.compute_chapter_tree(str(pdf_path), api_settings={})

    # 总-分-总: synthetic overview first, summary last, body in between.
    assert [c.title for c in tree] == [
        "全书导读",
        "第一章 基础",
        "第二章 进阶",
        "全书总结",
    ]
    overview_kp = tree[0].sections[0].knowledge_points[0]
    summary_kp = tree[-1].sections[0].knowledge_points[0]
    assert overview_kp.kind == "overview"
    assert summary_kp.kind == "summary"
    # 序言 occupies pages 1-2; that range is carried for synthesis input.
    assert overview_kp.matter_pages == [(1, 2)]
    assert summary_kp.matter_pages == [(11, 12)]

    # KP extraction ran only for body sections — never for 序言 / 附录.
    assert set(seen_sections) == {"1.1 概念", "1.2 应用", "2.1 深化"}


async def test_infer_skeleton_retries_once_on_invalid_output(monkeypatch):
    page_texts = [f"Page {i + 1} content" for i in range(10)]
    calls = {"n": 0}

    async def stub(_api, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            # page_end > total_pages → should fail validation and retry
            return json.dumps(
                {
                    "chapters": [
                        {
                            "title": "推断章 1",
                            "sections": [
                                {"title": "节 1.1", "page_start": 1, "page_end": 99}
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "chapters": [
                    {
                        "title": "推断章 1",
                        "sections": [
                            {"title": "节 1.1", "page_start": 1, "page_end": 5},
                            {"title": "节 1.2", "page_start": 6, "page_end": 10},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(builder, "complete_json", stub)
    layout = await builder._infer_skeleton_via_llm(page_texts, total_pages=10, api_settings={})
    assert calls["n"] == 2
    assert len(layout) == 1
    assert [s.title for s in layout[0].sections] == ["节 1.1", "节 1.2"]
    assert layout[0].sections[0].page_start == 1
    assert layout[0].sections[1].page_end == 10


async def test_infer_skeleton_raises_after_retry_exhausted(monkeypatch):
    async def stub(_api, _messages):
        return "not json at all"

    monkeypatch.setattr(builder, "complete_json", stub)
    with pytest.raises(ValueError, match="推断章节骨架失败"):
        await builder._infer_skeleton_via_llm([f"P{i}" for i in range(5)], total_pages=5, api_settings={})


async def test_compute_chapter_tree_falls_back_to_llm_skeleton_when_no_outline(
    tmp_path, monkeypatch
):
    pdf_path = _make_fixture_pdf_no_outline(tmp_path)

    skeleton_response = json.dumps(
        {
            "chapters": [
                {
                    "title": "推断章 1",
                    "sections": [
                        {"title": "节 1.1", "page_start": 1, "page_end": 6},
                        {"title": "节 1.2", "page_start": 7, "page_end": 12},
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )

    async def stub(_api, messages):
        if _is_skeleton_call(messages):
            return skeleton_response
        user_msg = messages[-1]["content"]
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        assert m, f"unexpected user prompt: {user_msg!r}"
        ps, pe = int(m.group(1)), int(m.group(2))
        return _stub_kp_response(ps, pe, count=3)

    monkeypatch.setattr(builder, "complete_json", stub)

    tree = await builder.compute_chapter_tree(str(pdf_path), api_settings={})

    assert tree[0].title == builder.OVERVIEW_TITLE
    assert tree[-1].title == builder.SUMMARY_TITLE
    body = tree[1:-1]
    assert len(body) == 1
    assert [s.title for s in body[0].sections] == ["节 1.1", "节 1.2"]
    for sec in body[0].sections:
        assert 1 <= len(sec.knowledge_points) <= 3
        for kp in sec.knowledge_points:
            assert sec.knowledge_points[0].page_start >= 1
            assert kp.page_end >= kp.page_start


def test_extract_md_splits_into_virtual_pages(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("a" * 1500 + "b" * 1500 + "c" * 500, encoding="utf-8")
    page_texts, total = builder._extract_md(str(md))
    assert total == 3
    assert page_texts[0] == "a" * 1500
    assert page_texts[1] == "b" * 1500
    assert page_texts[2] == "c" * 500


def test_extract_md_raises_on_empty_file(tmp_path):
    md = tmp_path / "empty.md"
    md.write_text("   \n  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="Markdown 文件为空"):
        builder._extract_md(str(md))


async def test_compute_chapter_tree_runs_section_extraction_concurrently(tmp_path, monkeypatch):
    """Issue 17: total wall-time ≈ max(section time) × ⌈N / concurrency⌉,
    not sum. Fixture PDF has 4 sections; each stub sleeps 0.3s. With
    concurrency=5 they should all run in parallel → < 0.6s, well under
    the serial 1.2s baseline."""
    import asyncio
    import time

    pdf_path = _make_fixture_pdf(tmp_path)

    async def slow_stub(_api, messages):
        user_msg = messages[-1]["content"]
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        assert m
        ps, pe = int(m.group(1)), int(m.group(2))
        await asyncio.sleep(0.3)
        return _stub_kp_response(ps, pe, count=3)

    monkeypatch.setattr(builder, "complete_json", slow_stub)

    t0 = time.monotonic()
    tree = await builder.compute_chapter_tree(str(pdf_path), api_settings={})
    elapsed = time.monotonic() - t0

    body = tree[1:-1]  # strip synthetic 全书导读/全书总结
    assert len(body) == 2  # 2 chapters
    total_sections = sum(len(ch.sections) for ch in body)
    assert total_sections == 4
    # Serial would be 4 × 0.3 = 1.2s. Parallel should be ~0.3s + overhead.
    assert elapsed < 0.8, f"expected <0.8s with concurrency, got {elapsed:.2f}s"


async def test_compute_chapter_tree_aggregates_section_failures(tmp_path, monkeypatch):
    """Issue 17: a single section failure surfaces as a composite ValueError
    naming how many failed."""
    pdf_path = _make_fixture_pdf(tmp_path)

    call_count = {"n": 0}

    async def flaky_stub(_api, messages):
        # Bypass skeleton calls; only the KP-extraction calls are flaky.
        if "推断这份资料合理的两层章节骨架" in messages[0]["content"]:
            return ""  # not used by fixture (it has TOC)
        call_count["n"] += 1
        # Fail one specific section consistently (both initial + retry).
        user_msg = messages[-1]["content"]
        if "Section 2.1" in user_msg:
            return "garbage not json"
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        ps, pe = int(m.group(1)), int(m.group(2))
        return _stub_kp_response(ps, pe, count=3)

    monkeypatch.setattr(builder, "complete_json", flaky_stub)

    with pytest.raises(ValueError, match=r"\d+/\d+ 个 Section 切分失败"):
        await builder.compute_chapter_tree(str(pdf_path), api_settings={})


async def test_compute_chapter_tree_reports_progress_per_section(tmp_path, monkeypatch):
    """Issue 20: on_progress is called once with (0, total) and once per
    completed section, ending at (total, total)."""
    pdf_path = _make_fixture_pdf(tmp_path)

    async def stub(_api, messages):
        user_msg = messages[-1]["content"]
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        ps, pe = int(m.group(1)), int(m.group(2))
        return _stub_kp_response(ps, pe, count=3)

    monkeypatch.setattr(builder, "complete_json", stub)

    events: list[tuple[int, int]] = []

    async def on_prog(d, t):
        events.append((d, t))

    await builder.compute_chapter_tree(str(pdf_path), api_settings={}, on_progress=on_prog)
    # fixture has 4 sections
    assert events[0] == (0, 4)
    assert events[-1] == (4, 4)
    # all reported (done, total) pairs have done in 0..4 monotonically
    dones = [d for d, _ in events]
    assert sorted(dones) == dones
    assert all(t == 4 for _, t in events)


async def test_compute_chapter_tree_routes_markdown_via_skeleton(tmp_path, monkeypatch):
    md = tmp_path / "course.md"
    md.write_text(
        "# 几何基础\n\n三角形内角和为 180 度。\n\n" * 200, encoding="utf-8"
    )

    skeleton_response = json.dumps(
        {
            "chapters": [
                {
                    "title": "几何",
                    "sections": [
                        {"title": "三角形", "page_start": 1, "page_end": 2},
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )

    async def stub(_api, messages):
        if _is_skeleton_call(messages):
            return skeleton_response
        user_msg = messages[-1]["content"]
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        assert m, f"unexpected user prompt: {user_msg!r}"
        ps, pe = int(m.group(1)), int(m.group(2))
        return _stub_kp_response(ps, pe, count=3)

    monkeypatch.setattr(builder, "complete_json", stub)

    tree = await builder.compute_chapter_tree(str(md), api_settings={})
    assert tree[0].title == builder.OVERVIEW_TITLE
    assert tree[-1].title == builder.SUMMARY_TITLE
    body = tree[1:-1]
    assert len(body) == 1
    assert body[0].title == "几何"
    assert len(body[0].sections) == 1
    assert body[0].sections[0].title == "三角形"
    assert 1 <= len(body[0].sections[0].knowledge_points) <= 3


async def _make_course(pdf_path: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="build test",
            source_pdf_path=pdf_path,
            generation_status=GenerationStatus.running,
        )
        db.add(course)
        await db.commit()
        return course.id


async def _drop_course(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()


async def test_build_chapter_tree_persists_synthetic_matter_kps(
    tmp_path, monkeypatch
):
    pdf_path = _make_fixture_pdf_with_matter(tmp_path)
    course_id = await _make_course(str(pdf_path))
    try:
        async def kp_stub(_api, messages):
            user_msg = messages[-1]["content"]
            pr = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
            return _stub_kp_response(int(pr.group(1)), int(pr.group(2)), count=3)

        async def _noop_index(*a, **k):
            return 0

        async def _noop_prewarm(*a, **k):
            return 0

        monkeypatch.setattr(builder, "complete_json", kp_stub)
        monkeypatch.setattr(builder, "index_course_chunks", _noop_index)
        monkeypatch.setattr(builder, "prewarm_kp_materials", _noop_prewarm)

        await builder.build_chapter_tree(course_id, str(pdf_path))

        async with SessionLocal() as db:
            chapters = (
                (
                    await db.execute(
                        select(Chapter)
                        .where(Chapter.course_id == course_id)
                        .order_by(Chapter.order_index)
                    )
                )
                .scalars()
                .all()
            )
            titles = [c.title for c in chapters]
            assert titles[0] == builder.OVERVIEW_TITLE
            assert titles[-1] == builder.SUMMARY_TITLE
            assert chapters[0].order_index == 0
            assert chapters[-1].order_index == len(chapters) - 1

            async def _only_kp(chapter: Chapter) -> KnowledgePoint:
                secs = (
                    (
                        await db.execute(
                            select(Section).where(
                                Section.chapter_id == chapter.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(secs) == 1
                kps = (
                    (
                        await db.execute(
                            select(KnowledgePoint).where(
                                KnowledgePoint.section_id == secs[0].id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(kps) == 1
                return kps[0]

            overview_kp = await _only_kp(chapters[0])
            summary_kp = await _only_kp(chapters[-1])
            assert overview_kp.boundary == {
                "kind": "overview",
                "matter_pages": [[1, 2]],
            }
            assert summary_kp.boundary == {
                "kind": "summary",
                "matter_pages": [[11, 12]],
            }
            assert "page_start" not in overview_kp.boundary

            # A body KP keeps the normal page-range boundary.
            body_secs = (
                (
                    await db.execute(
                        select(Section).where(
                            Section.chapter_id == chapters[1].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            body_kps = (
                (
                    await db.execute(
                        select(KnowledgePoint).where(
                            KnowledgePoint.section_id == body_secs[0].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "page_start" in body_kps[0].boundary
            assert "kind" not in body_kps[0].boundary
    finally:
        await _drop_course(course_id)


# ---------- EPUB source support (reuses the fitz/PDF path) ----------

from app.kp.loader import extract_kp_text  # noqa: E402
from tests.epub_fixture import make_epub  # noqa: E402


def _make_fixture_epub(tmp_path: Path) -> Path:
    out = tmp_path / "fixture.epub"
    make_epub(out)
    return out


async def test_compute_chapter_tree_from_epub(tmp_path, monkeypatch):
    """`.epub` is not markdown, so it flows through the existing fitz
    path: get_toc() → _parse_toc_layout → 2 chapters × 2 sections,
    bracketed by synthetic 全书导读/全书总结."""
    epub_path = _make_fixture_epub(tmp_path)

    async def stub(_api, messages):
        user_msg = messages[-1]["content"]
        m = re.search(r"页码范围：(\d+) - (\d+)", user_msg)
        assert m, f"unexpected user prompt: {user_msg!r}"
        return _stub_kp_response(int(m.group(1)), int(m.group(2)), count=3)

    monkeypatch.setattr(builder, "complete_json", stub)

    tree = await builder.compute_chapter_tree(str(epub_path), api_settings={})

    assert tree[0].title == builder.OVERVIEW_TITLE
    assert tree[-1].title == builder.SUMMARY_TITLE
    body = tree[1:-1]
    assert [c.title for c in body] == ["第一章 力学", "第二章 测量"]
    assert all(len(ch.sections) == 2 for ch in body)
    for ch in body:
        for sec in ch.sections:
            assert 1 <= len(sec.knowledge_points) <= 3
            for kp in sec.knowledge_points:
                assert kp.title.strip()
                assert kp.page_end >= kp.page_start >= 1
                assert kp.kind is None


def test_extract_kp_text_epub_uses_fitz_not_markdown(tmp_path):
    """extract_kp_text must slice EPUB by fitz pages (not the markdown
    char-offset virtual-page path). Each section is its own page."""
    epub_path = str(_make_fixture_epub(tmp_path))

    page1 = extract_kp_text(epub_path, 1, 1)
    assert "MARK_S11" in page1
    assert "MARK_S12" not in page1  # not a raw whole-file slice

    page3 = extract_kp_text(epub_path, 3, 3)
    assert "MARK_S21" in page3
    assert "MARK_S11" not in page3
