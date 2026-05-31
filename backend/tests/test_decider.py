import uuid

import pytest
from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.kp import decider
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    KPStatus,
    Section,
    Weakness,
    WeaknessSource,
)


# ---------- pure-function tests ----------


def test_aggregate_status_empty_returns_untouched():
    assert decider.aggregate_status([]) == KPStatus.untouched


def test_aggregate_status_all_passed():
    assert (
        decider.aggregate_status([KPStatus.passed, KPStatus.passed])
        == KPStatus.passed
    )


def test_aggregate_status_partial_passed_is_in_progress():
    assert (
        decider.aggregate_status([KPStatus.passed, KPStatus.untouched])
        == KPStatus.in_progress
    )


def test_aggregate_status_any_in_progress():
    assert (
        decider.aggregate_status([KPStatus.untouched, KPStatus.in_progress])
        == KPStatus.in_progress
    )


def test_aggregate_status_all_untouched():
    assert (
        decider.aggregate_status([KPStatus.untouched, KPStatus.untouched])
        == KPStatus.untouched
    )


def test_suggestion_for_high_score_indicates_pass():
    msg = decider.suggestion_for_score(85)
    assert "已掌握" in msg


def test_suggestion_for_low_score_indicates_weakness():
    msg = decider.suggestion_for_score(50)
    assert "薄弱" in msg or "再练" in msg


# ---------- integration test ----------


async def _build_course_with_kps() -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Create a course with 1 chapter / 1 section / 3 KPs.

    Returns (course_id, [kp_id_0, kp_id_1, kp_id_2]).
    """
    async with SessionLocal() as db:
        course = Course(
            name="decider course",
            source_pdf_path="/tmp/decider.pdf",
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()
        chapter = Chapter(course_id=course.id, title="ch", order_index=0)
        db.add(chapter)
        await db.flush()
        section = Section(chapter_id=chapter.id, title="sec", order_index=0)
        db.add(section)
        await db.flush()
        kps = [
            KnowledgePoint(
                section_id=section.id, title=f"kp{i}", order_index=i, boundary={}
            )
            for i in range(3)
        ]
        for kp in kps:
            db.add(kp)
        await db.flush()
        await db.commit()
        return course.id, [kp.id for kp in kps]


async def _cleanup_course(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()


@pytest.mark.asyncio
async def test_decider_full_flow_grading_skipped_upsert_and_aggregation():
    """Single integration test covering:
    - record_grading_weakness_if_low writes a 'grading' row when score < 75,
      skips when >= 75
    - repeated low scores upsert into the same row (no accumulation)
    - upsert_weakness with a different source coexists on the same KP
    - section_status_aggregation reflects KP.status changes
    """
    course_id, kp_ids = await _build_course_with_kps()
    try:
        # --- weakness writes ---
        async with SessionLocal() as db:
            # KP 0: low score → grading weakness inserted
            await decider.record_grading_weakness_if_low(
                db, kp_id=kp_ids[0], overall_score=40
            )
            await db.commit()
            n = (
                await db.execute(
                    select(func.count(Weakness.id)).where(
                        Weakness.kp_id == kp_ids[0],
                        Weakness.source == WeaknessSource.grading,
                    )
                )
            ).scalar_one()
            assert n == 1

            # KP 0: second low score on same KP → upsert (still 1 row), description refreshed
            await decider.record_grading_weakness_if_low(
                db, kp_id=kp_ids[0], overall_score=30
            )
            await db.commit()
            rows = (
                await db.execute(
                    select(Weakness).where(
                        Weakness.kp_id == kp_ids[0],
                        Weakness.source == WeaknessSource.grading,
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert "30/100" in rows[0].description

            # KP 1: high score → no weakness row
            await decider.record_grading_weakness_if_low(
                db, kp_id=kp_ids[1], overall_score=85
            )
            await db.commit()
            n_kp1 = (
                await db.execute(
                    select(func.count(Weakness.id)).where(
                        Weakness.kp_id == kp_ids[1],
                    )
                )
            ).scalar_one()
            assert n_kp1 == 0

            # KP 0: also write a skipped weakness — different source, coexists
            await decider.upsert_weakness(
                db,
                course_id=course_id,
                kp_id=kp_ids[0],
                source=WeaknessSource.skipped,
                description="用户跳过未掌握的知识点（30/100）",
            )
            await db.commit()
            sources = {
                w.source
                for w in (
                    await db.execute(
                        select(Weakness).where(
                            Weakness.kp_id == kp_ids[0],
                        )
                    )
                ).scalars().all()
            }
            assert sources == {WeaknessSource.grading, WeaknessSource.skipped}

        # --- aggregation reflects KP status ---
        async with SessionLocal() as db:
            result = await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids))
            )
            for kp in result.scalars().all():
                kp.status = KPStatus.passed
            await db.commit()

        async with SessionLocal() as db:
            statuses_q = await db.execute(
                select(KnowledgePoint.status).where(KnowledgePoint.id.in_(kp_ids))
            )
            statuses = [row[0] for row in statuses_q.all()]
            assert decider.aggregate_status(statuses) == KPStatus.passed
    finally:
        await _cleanup_course(course_id)
