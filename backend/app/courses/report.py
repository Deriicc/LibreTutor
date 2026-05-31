"""Aggregation helpers feeding the teacher diary (ADR-0023).

`_compute_progress` is consumed by `app.kp.diarist`;
`_list_submissions_grouped` is retained for attempt-pinning tests. The
old `/report` endpoint and its `build_report`/`_list_weaknesses`
aggregators were removed when the diary book replaced the report page.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kp.decider import aggregate_status
from app.models import (
    Chapter,
    Grade,
    KnowledgePoint,
    KPExerciseSet,
    KPStatus,
    Message,
    Section,
    Submission,
    SubmissionStatus,
)


async def _compute_progress(
    course_id: uuid.UUID, db: AsyncSession
) -> dict[str, Any]:
    # Synthetic 全书导读/全书总结 KPs are read-only and never pass —
    # exclude them so completion can reach 100%, matching the canonical
    # filter in courses/router.py list_courses and admin/router.py.
    kp_q = await db.execute(
        select(KnowledgePoint.status)
        .join(Section, KnowledgePoint.section_id == Section.id)
        .join(Chapter, Section.chapter_id == Chapter.id)
        .where(Chapter.course_id == course_id)
        .where(KnowledgePoint.boundary["kind"].astext.is_(None))
    )
    kp_statuses = [row[0] for row in kp_q.all()]
    kp_total = len(kp_statuses)
    kp_passed = sum(1 for s in kp_statuses if s == KPStatus.passed)

    # chapter_passed via aggregate over its sections' aggregate over its KPs
    chapters_q = await db.execute(
        select(Chapter.id, Section.id, KnowledgePoint.status)
        .join(Section, Section.chapter_id == Chapter.id)
        .join(KnowledgePoint, KnowledgePoint.section_id == Section.id)
        .where(Chapter.course_id == course_id)
        .where(KnowledgePoint.boundary["kind"].astext.is_(None))
        .order_by(Chapter.order_index, Section.order_index, KnowledgePoint.order_index)
    )
    by_chapter: dict[uuid.UUID, dict[uuid.UUID, list[KPStatus]]] = {}
    for ch_id, sec_id, st in chapters_q.all():
        by_chapter.setdefault(ch_id, {}).setdefault(sec_id, []).append(st)
    chapter_total = len(by_chapter)
    chapter_passed = 0
    for sections in by_chapter.values():
        sec_statuses = [aggregate_status(kps) for kps in sections.values()]
        if aggregate_status(sec_statuses) == KPStatus.passed:
            chapter_passed += 1

    # Study time: per (KP, attempt), max(created_at) - min(created_at),
    # summed. Grouping by attempt — not just kp_id — keeps the dead gap
    # between a failed round and a later retry out of the total (a
    # Mon→Fri retry must not read as days of study). Still a coarse upper
    # bound: idle time inside a single round is not subtracted.
    time_q = await db.execute(
        select(
            func.min(Message.created_at),
            func.max(Message.created_at),
        )
        .join(KnowledgePoint, Message.kp_id == KnowledgePoint.id)
        .join(Section, KnowledgePoint.section_id == Section.id)
        .join(Chapter, Section.chapter_id == Chapter.id)
        .where(Chapter.course_id == course_id)
        .group_by(Message.kp_id, Message.attempt)
    )
    total_seconds = 0
    for mn, mx in time_q.all():
        if mn is not None and mx is not None and mx > mn:
            total_seconds += (mx - mn).total_seconds()

    return {
        "kp_passed": kp_passed,
        "kp_total": kp_total,
        "chapter_passed": chapter_passed,
        "chapter_total": chapter_total,
        "study_minutes": round(total_seconds / 60),
    }


async def _list_submissions_grouped(
    course_id: uuid.UUID, db: AsyncSession
) -> list[dict[str, Any]]:
    """Return KPs with their submission history (most recent first)."""
    sub_q = await db.execute(
        select(Submission, KnowledgePoint.title, KnowledgePoint.order_index)
        .join(KnowledgePoint, KnowledgePoint.id == Submission.kp_id)
        .join(Section, Section.id == KnowledgePoint.section_id)
        .join(Chapter, Chapter.id == Section.chapter_id)
        .where(
            Chapter.course_id == course_id,
        )
        .order_by(
            KnowledgePoint.order_index.asc(),
            Submission.submitted_at.desc(),
        )
    )
    rows = sub_q.all()
    if not rows:
        return []

    # need each submission's grade
    sub_ids = [s.id for s, _, _ in rows]
    grade_q = await db.execute(select(Grade).where(Grade.submission_id.in_(sub_ids)))
    grades_by_sub = {g.submission_id: g for g in grade_q.scalars().all()}

    # Pull the exact exercise set each submission was answering — keyed by
    # (kp_id, attempt) so retries don't leak the current attempt's questions
    # onto an old submission.
    needed_keys = {(s.kp_id, s.attempt) for s, _, _ in rows}
    contents_by_key: dict[tuple[uuid.UUID, int], list[dict[str, Any]]] = {}
    if needed_keys:
        kp_ids = list({k for k, _ in needed_keys})
        es_q = await db.execute(
            select(KPExerciseSet).where(KPExerciseSet.kp_id.in_(kp_ids))
        )
        for es in es_q.scalars().all():
            contents_by_key[(es.kp_id, es.attempt)] = list(es.exercises)

    grouped: dict[uuid.UUID, dict[str, Any]] = {}
    for sub, kp_title, _order in rows:
        if sub.kp_id not in grouped:
            grouped[sub.kp_id] = {
                "kp_id": sub.kp_id,
                "kp_title": kp_title,
                "submissions": [],
            }
        grade = grades_by_sub.get(sub.id)
        grouped[sub.kp_id]["submissions"].append(
            {
                "id": sub.id,
                "attempt": sub.attempt,
                "submitted_at": sub.submitted_at,
                "completed_at": sub.completed_at,
                "status": sub.status.value,
                "overall_score": grade.overall_score if grade else None,
                "exercises": contents_by_key.get((sub.kp_id, sub.attempt), []),
                "answers": list(sub.answers),
                "grade": (
                    {
                        "per_question": grade.per_question,
                        "overall_score": grade.overall_score,
                        "overall_feedback": grade.overall_feedback,
                    }
                    if grade
                    else None
                ),
            }
        )
    return list(grouped.values())
