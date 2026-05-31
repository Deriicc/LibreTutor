"""Course-build hook: spawn KP material generation in parallel.

After `build_chapter_tree` commits the chapter tree, this module's
`prewarm_kp_materials` fires per-KP material generation under a
concurrency limit. The chat dialogue (Layer 3 checklist/keyphrases)
and the assessor (which reads checklist) both depend on KPMaterial
existing; running this in the background gives them a cache hit by
the time the student opens a KP.

Exercise sets are NOT generated here — they're tailored after the
assessor produces covered_concepts (see materializer.tailor_exercise_set).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.kp.loader import extract_kp_text
from app.kp.materializer import (
    materialize_book_overview_material,
    materialize_kp_material,
)
from app.models import (
    Chapter,
    Course,
    KnowledgePoint,
    KPMaterial,
    Section,
)
from app.user_llm import load_api_settings

logger = logging.getLogger(__name__)


async def _materialize_one(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    kp_title: str,
    source_path: str,
    page_start: int,
    page_end: int,
    api_settings: dict | None,
    sema: asyncio.Semaphore,
) -> None:
    async with sema:
        try:
            async with SessionLocal() as db:
                if await db.get(KPMaterial, kp_id) is not None:
                    return
                await materialize_kp_material(
                    db,
                    course_id=course_id,
                    kp_id=kp_id,
                    kp_title=kp_title,
                    pdf_path=source_path,
                    page_start=page_start,
                    page_end=page_end,
                    api_settings=api_settings,
                )
        except Exception:  # noqa: BLE001
            logger.exception("prewarm_kp_materials failed for kp %s", kp_id)


async def _materialize_book_one(
    kp_id: uuid.UUID,
    kind: str,
    outline_text: str,
    source_path: str,
    matter_pages: list[list[int]],
    api_settings: dict | None,
    sema: asyncio.Semaphore,
) -> None:
    async with sema:
        try:
            matter_text = "\n\n".join(
                extract_kp_text(source_path, int(s), int(e))
                for s, e in matter_pages
            ).strip()
            async with SessionLocal() as db:
                if await db.get(KPMaterial, kp_id) is not None:
                    return
                await materialize_book_overview_material(
                    db,
                    kp_id=kp_id,
                    kind=kind,
                    outline_text=outline_text,
                    matter_text=matter_text,
                    api_settings=api_settings,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "prewarm book-overview failed for kp %s", kp_id
            )


async def _course_outline_text(course_id: uuid.UUID) -> str:
    """Compact whole-book outline (body only — synthetic 导读/总结 KPs are
    excluded) fed to the book-level material generator."""
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
        lines: list[str] = []
        for ch in chapters:
            sections = (
                (
                    await db.execute(
                        select(Section)
                        .where(Section.chapter_id == ch.id)
                        .order_by(Section.order_index)
                    )
                )
                .scalars()
                .all()
            )
            chapter_lines: list[str] = []
            for sec in sections:
                kps = (
                    (
                        await db.execute(
                            select(KnowledgePoint)
                            .where(KnowledgePoint.section_id == sec.id)
                            .order_by(KnowledgePoint.order_index)
                        )
                    )
                    .scalars()
                    .all()
                )
                kp_lines = [
                    f"    - {kp.title}"
                    + (
                        f"：{(kp.boundary or {}).get('description')}"
                        if (kp.boundary or {}).get("description")
                        else ""
                    )
                    for kp in kps
                    if not (kp.boundary or {}).get("kind")
                ]
                if kp_lines:
                    chapter_lines.append(f"  {sec.title}")
                    chapter_lines.extend(kp_lines)
            if chapter_lines:
                lines.append(ch.title)
                lines.extend(chapter_lines)
        return "\n".join(lines)


async def prewarm_kp_materials(course_id: uuid.UUID) -> int:
    """Generate KPMaterial for every KP in this course, in parallel under
    the same concurrency limit as KP extraction. Returns number of KPs
    that have a material row at exit time (existing rows count as warmed).
    """
    async with SessionLocal() as db:
        course = await db.get(Course, course_id)
        if course is None:
            return 0
        api_settings = await load_api_settings(db)
        rows = (
            await db.execute(
                select(KnowledgePoint, Course.source_pdf_path)
                .join(Section, KnowledgePoint.section_id == Section.id)
                .join(Chapter, Section.chapter_id == Chapter.id)
                .join(Course, Chapter.course_id == Course.id)
                .where(Chapter.course_id == course_id)
            )
        ).all()

    has_synthetic = any(
        (kp.boundary or {}).get("kind") for kp, _ in rows
    )
    outline_text = (
        await _course_outline_text(course_id) if has_synthetic else ""
    )

    sema = asyncio.Semaphore(settings.kp_extraction_concurrency)
    tasks = []
    for kp, source_path in rows:
        boundary = kp.boundary or {}
        kind = boundary.get("kind")
        if kind in ("overview", "summary"):
            tasks.append(
                _materialize_book_one(
                    kp.id,
                    kind,
                    outline_text,
                    source_path,
                    boundary.get("matter_pages") or [],
                    api_settings,
                    sema,
                )
            )
            continue
        ps = int(boundary.get("page_start") or 1)
        pe = int(boundary.get("page_end") or ps)
        tasks.append(
            _materialize_one(
                course_id,
                kp.id,
                kp.title,
                source_path,
                ps,
                pe,
                api_settings,
                sema,
            )
        )
    await asyncio.gather(*tasks, return_exceptions=True)

    async with SessionLocal() as db:
        n = (
            await db.execute(
                select(func.count(KPMaterial.kp_id))
                .join(KnowledgePoint, KPMaterial.kp_id == KnowledgePoint.id)
                .join(Section, KnowledgePoint.section_id == Section.id)
                .join(Chapter, Section.chapter_id == Chapter.id)
                .where(Chapter.course_id == course_id)
            )
        ).scalar_one()
    return int(n)
