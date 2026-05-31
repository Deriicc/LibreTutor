import uuid

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import reset_inflight_submissions
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    Section,
    Submission,
    SubmissionStatus,
)


async def _setup_fixture_kp() -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="lifespan test",
            source_pdf_path="/tmp/lifespan_test.pdf",
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
        kp = KnowledgePoint(
            section_id=section.id, title="kp", order_index=0, boundary={}
        )
        db.add(kp)
        await db.commit()
        return course.id, kp.id


async def test_reset_inflight_submissions_only_touches_pending_and_running():
    course_id, kp_id = await _setup_fixture_kp()
    try:
        async with SessionLocal() as db:
            pending = Submission(
                kp_id=kp_id, answers=[], status=SubmissionStatus.pending
            )
            running = Submission(
                kp_id=kp_id, answers=[], status=SubmissionStatus.running
            )
            done = Submission(
                kp_id=kp_id, answers=[], status=SubmissionStatus.done
            )
            failed = Submission(
                kp_id=kp_id,
                answers=[],
                status=SubmissionStatus.failed,
                error="prior failure",
            )
            db.add_all([pending, running, done, failed])
            await db.commit()
            ids = {
                "pending": pending.id,
                "running": running.id,
                "done": done.id,
                "failed": failed.id,
            }

        n = await reset_inflight_submissions()
        assert n == 2

        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Submission).where(Submission.id.in_(ids.values()))
                )
            ).scalars().all()
            by_id = {row.id: row for row in rows}

            # pending → failed with restart marker
            p = by_id[ids["pending"]]
            assert p.status == SubmissionStatus.failed
            assert p.error and "服务重启" in p.error
            assert p.completed_at is not None

            # running → failed with restart marker
            r = by_id[ids["running"]]
            assert r.status == SubmissionStatus.failed
            assert r.error and "服务重启" in r.error
            assert r.completed_at is not None

            # done untouched
            d = by_id[ids["done"]]
            assert d.status == SubmissionStatus.done
            assert d.error is None

            # already-failed untouched (error message preserved)
            f = by_id[ids["failed"]]
            assert f.status == SubmissionStatus.failed
            assert f.error == "prior failure"
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()
