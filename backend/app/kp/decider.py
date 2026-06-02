"""CompletionDecider + WeaknessPool helpers + chapter-tree status aggregation."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    KnowledgePoint,
    KPStatus,
    Section,
    Weakness,
    WeaknessSource,
)


PASS_THRESHOLD = 75


def aggregate_status(children: list[KPStatus]) -> KPStatus:
    """Roll up a list of child statuses into a parent status.

    Rules:
      - empty → untouched
      - all passed → passed
      - any passed or in_progress → in_progress (partial = in progress)
      - else → untouched
    """
    if not children:
        return KPStatus.untouched
    if all(s == KPStatus.passed for s in children):
        return KPStatus.passed
    if any(s in (KPStatus.passed, KPStatus.in_progress) for s in children):
        return KPStatus.in_progress
    return KPStatus.untouched


_SUGGESTION = {
    "zh": {
        "pass": "已掌握（{score}/100），可进入下一节。",
        "low": "分数偏低（{score}/100），还有薄弱点。建议「再练一道」巩固，或跳过。",
    },
    "en": {
        "pass": "Mastered ({score}/100) — you can move on to the next section.",
        "low": "Score is low ({score}/100); there are still weak spots. "
        "Try “redo a set” to reinforce, or skip.",
    },
}


def suggestion_for_score(overall_score: int, lang: str = "zh") -> str:
    table = _SUGGESTION.get(lang, _SUGGESTION["zh"])
    key = "pass" if overall_score >= PASS_THRESHOLD else "low"
    return table[key].format(score=overall_score)


async def upsert_weakness(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    source: WeaknessSource,
    description: str,
) -> None:
    """Insert or refresh a Weakness row.

    Why upsert: same (kp, source) repeats are noise — the report just
    needs to know the learner is weak on that KP, not how many times
    we've recorded it. Updating description+created_at keeps the freshest
    context (e.g. most recent low score) visible.
    """
    values = {
        "id": uuid.uuid4(),
        "course_id": course_id,
        "kp_id": kp_id,
        "source": source,
        "description": description,
    }
    stmt = pg_insert(Weakness).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_weakness_kp_source",
        set_={
            "description": stmt.excluded.description,
            "created_at": func.now(),
        },
    )
    await db.execute(stmt)


async def record_grading_weakness_if_low(
    db: AsyncSession,
    *,
    kp_id: uuid.UUID,
    overall_score: int,
) -> None:
    """Called by grader on submission completion. Upserts a grading
    weakness when the score is below threshold."""
    if overall_score >= PASS_THRESHOLD:
        return

    course_id_q = await db.execute(
        select(Chapter.course_id)
        .join(Section, Section.chapter_id == Chapter.id)
        .join(KnowledgePoint, KnowledgePoint.section_id == Section.id)
        .where(KnowledgePoint.id == kp_id)
    )
    course_id = course_id_q.scalar_one_or_none()
    if course_id is None:
        return

    await upsert_weakness(
        db,
        course_id=course_id,
        kp_id=kp_id,
        source=WeaknessSource.grading,
        description=f"评分低于阈值（{overall_score}/100）",
    )


