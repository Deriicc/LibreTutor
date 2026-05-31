"""Course position queries.

Pure read-side: where does a given KP sit in the course tree? Used by
chat Layer 3 to tell the LLM what came before and what comes next.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, KnowledgePoint, Section


async def get_kp_position(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[int, list[str], list[str]]:
    """Locate a KP within its course.

    Returns ``(position, prev_titles, next_titles)`` where ``position`` is
    1-based. Returns ``(1, [], [])`` if the KP is not part of the course
    (e.g. test fixtures where the KP exists in isolation).
    """
    result = await db.execute(
        select(KnowledgePoint.id, KnowledgePoint.title)
        .join(Section, KnowledgePoint.section_id == Section.id)
        .join(Chapter, Section.chapter_id == Chapter.id)
        .where(Chapter.course_id == course_id)
        .order_by(
            Chapter.order_index, Section.order_index, KnowledgePoint.order_index
        )
    )
    rows = result.all()
    ids = [r[0] for r in rows]
    titles = [r[1] for r in rows]
    try:
        idx = ids.index(kp_id)
    except ValueError:
        return 1, [], []
    return idx + 1, titles[:idx], titles[idx + 1 :]
