"""KP read-side helpers: fetch material + exercise set rows, extract PDF text.

Write-side (generation + persistence) lives in app.kp.materializer.
"""

from __future__ import annotations

import fitz  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgePoint, KPExerciseSet, KPMaterial


_MD_VIRTUAL_PAGE_CHARS = 1500  # must match builder.MD_VIRTUAL_PAGE_CHARS


async def get_kp_material(db: AsyncSession, kp_id) -> KPMaterial | None:
    """Fetch the teaching material for a KP. None if not yet generated."""
    return await db.get(KPMaterial, kp_id)


async def get_kp_exercise_set_at(
    db: AsyncSession, kp_id, attempt: int
) -> KPExerciseSet | None:
    """Fetch the exercise set at a specific (kp_id, attempt). Used by the
    grader (via Submission.attempt) and the report page when rendering
    historical questions."""
    return await db.get(KPExerciseSet, (kp_id, attempt))


async def get_live_kp_exercise_set(
    db: AsyncSession, kp_id
) -> KPExerciseSet | None:
    """Fetch the exercise set whose attempt matches `KnowledgePoint.current_attempt`.
    None if not yet generated."""
    kp = await db.get(KnowledgePoint, kp_id)
    if kp is None:
        return None
    res = await db.execute(
        select(KPExerciseSet).where(
            KPExerciseSet.kp_id == kp_id,
            KPExerciseSet.attempt == kp.current_attempt,
        )
    )
    return res.scalar_one_or_none()


def extract_kp_text(
    source_path: str, page_start: int, page_end: int, max_chars: int = 12000
) -> str:
    """Extract text for the KP page range. Dispatches PDF vs Markdown by suffix.

    Markdown sources have no native pages; the builder splits them into
    1500-char virtual pages, so we slice the same way to honor KP boundaries.
    """
    lower = source_path.lower()
    if lower.endswith(".md") or lower.endswith(".markdown"):
        with open(source_path, encoding="utf-8") as f:
            text = f.read()
        n_pages = max(1, (len(text) + _MD_VIRTUAL_PAGE_CHARS - 1) // _MD_VIRTUAL_PAGE_CHARS)
        ps = max(1, min(page_start, n_pages))
        pe = max(ps, min(page_end, n_pages))
        start = (ps - 1) * _MD_VIRTUAL_PAGE_CHARS
        end = pe * _MD_VIRTUAL_PAGE_CHARS
        return text[start:end][:max_chars]
    doc = fitz.open(source_path)
    try:
        if doc.page_count == 0:
            return ""
        ps = max(1, min(page_start, doc.page_count))
        pe = max(ps, min(page_end, doc.page_count))
        pages = [doc[i].get_text() for i in range(ps - 1, pe)]
        joined = "\n".join(pages)
        return joined[:max_chars]
    finally:
        doc.close()
