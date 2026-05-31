"""KPExerciseSet versioning by attempt + submission attempt pinning.
Persona is rendered live every turn (ADR-0023): config edits take
effect immediately, stale KPMaterial.layer2_snapshot is ignored."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.chat.socratic import _build_layer2
from app.courses.report import _compute_progress, _list_submissions_grouped
from app.db import SessionLocal
from app.kp.assessor import _load_history
from app.kp.loader import get_live_kp_exercise_set
from app.kp.router import _attempt_has_activity
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    Grade,
    KnowledgePoint,
    KPExerciseSet,
    KPMaterial,
    KPStatus,
    Message,
    MessageRole,
    Section,
    Submission,
    SubmissionStatus,
    TeacherConfig,
)


async def _setup_kp() -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="attempts test",
            source_pdf_path="/tmp/attempts.pdf",
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


async def test_attempt_versioning_keeps_history_and_grades_with_pinned_exercises():
    """End-to-end:
    1. attempt=1 exercise set + submission(attempt=1) + grade
    2. retry bumps current_attempt to 2; attempt=2 exercise set has different qs
    3. submit again at attempt=2
    4. report API returns each submission paired with the right exercises
    5. get_live_kp_exercise_set returns the attempt=2 row
    """
    course_id, kp_id = await _setup_kp()
    try:
        async with SessionLocal() as db:
            db.add(
                KPExerciseSet(
                    kp_id=kp_id,
                    attempt=1,
                    exercises=[
                        {"type": "mcq", "question": "v1 question", "correct_answer": "A"}
                    ],
                )
            )
            sub1 = Submission(
                kp_id=kp_id,
                attempt=1,
                answers=[{"index": 0, "answer": "A"}],
                status=SubmissionStatus.done,
            )
            db.add(sub1)
            await db.flush()
            db.add(
                Grade(
                    submission_id=sub1.id,
                    per_question=[{"index": 0, "score": 100, "feedback": "ok"}],
                    overall_score=100,
                    overall_feedback="v1 graded",
                )
            )
            await db.commit()
            sub1_id = sub1.id

        # simulate retry: bump current_attempt + write new exercise set
        async with SessionLocal() as db:
            kp = await db.get(KnowledgePoint, kp_id)
            kp.current_attempt = 2
            db.add(
                KPExerciseSet(
                    kp_id=kp_id,
                    attempt=2,
                    exercises=[
                        {"type": "mcq", "question": "v2 question", "correct_answer": "B"}
                    ],
                )
            )
            sub2 = Submission(
                kp_id=kp_id,
                attempt=2,
                answers=[{"index": 0, "answer": "B"}],
                status=SubmissionStatus.done,
            )
            db.add(sub2)
            await db.flush()
            db.add(
                Grade(
                    submission_id=sub2.id,
                    per_question=[{"index": 0, "score": 90, "feedback": "good"}],
                    overall_score=90,
                    overall_feedback="v2 graded",
                )
            )
            await db.commit()
            sub2_id = sub2.id

        # live exercise set is attempt=2
        async with SessionLocal() as db:
            live = await get_live_kp_exercise_set(db, kp_id)
            assert live is not None
            assert live.attempt == 2
            assert live.exercises[0]["question"] == "v2 question"

        # report API pairs each submission with its own attempt's exercises
        async with SessionLocal() as db:
            grouped = await _list_submissions_grouped(course_id, db)
        assert len(grouped) == 1
        subs = grouped[0]["submissions"]
        by_id = {s["id"]: s for s in subs}
        assert by_id[sub1_id]["attempt"] == 1
        assert by_id[sub1_id]["exercises"][0]["question"] == "v1 question"
        assert by_id[sub1_id]["answers"] == [{"index": 0, "answer": "A"}]
        assert by_id[sub2_id]["attempt"] == 2
        assert by_id[sub2_id]["exercises"][0]["question"] == "v2 question"
        assert by_id[sub2_id]["answers"] == [{"index": 0, "answer": "B"}]
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_messages_are_scoped_per_attempt():
    """Regression: chat messages must not leak across retry rounds.
    Assessor history is per-attempt, and the diary activity-guard no
    longer reports a fresh round as "had teaching" just because an
    earlier round did."""
    course_id, kp_id = await _setup_kp()
    try:
        async with SessionLocal() as db:
            db.add_all(
                [
                    Message(
                        kp_id=kp_id, attempt=1,
                        role=MessageRole.user, content="round1 q",
                    ),
                    Message(
                        kp_id=kp_id, attempt=1,
                        role=MessageRole.assistant, content="round1 a",
                    ),
                    Message(
                        kp_id=kp_id, attempt=2,
                        role=MessageRole.user, content="round2 q",
                    ),
                ]
            )
            await db.commit()

        async with SessionLocal() as db:
            h1 = await _load_history(kp_id, 1, db)
            h2 = await _load_history(kp_id, 2, db)
            assert [m.content for m in h1] == ["round1 q", "round1 a"]
            assert [m.content for m in h2] == ["round2 q"]

            # attempt 2 has its own message → True; attempt 3 has no
            # message and no submission → False, even though 1 & 2 chatted.
            assert await _attempt_has_activity(kp_id, 2, db) is True
            assert await _attempt_has_activity(kp_id, 3, db) is False
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_study_minutes_does_not_span_across_attempts():
    """Regression: study time is summed per (kp, attempt), so a Monday
    round 1 + Friday round 2 reads as the two short spans, not the
    multi-day envelope between them."""
    course_id, kp_id = await _setup_kp()
    try:
        t0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        async with SessionLocal() as db:
            db.add_all(
                [
                    Message(
                        kp_id=kp_id, attempt=1, role=MessageRole.user,
                        content="r1 a", created_at=t0,
                    ),
                    Message(
                        kp_id=kp_id, attempt=1, role=MessageRole.assistant,
                        content="r1 b", created_at=t0 + timedelta(minutes=10),
                    ),
                    Message(
                        kp_id=kp_id, attempt=2, role=MessageRole.user,
                        content="r2 a", created_at=t0 + timedelta(days=4),
                    ),
                    Message(
                        kp_id=kp_id, attempt=2, role=MessageRole.assistant,
                        content="r2 b",
                        created_at=t0 + timedelta(days=4, minutes=10),
                    ),
                ]
            )
            await db.commit()

        async with SessionLocal() as db:
            progress = await _compute_progress(course_id, db)
        # Two 10-min spans = 20, not ~4 days (the old kp_id-only envelope).
        assert progress["study_minutes"] == 20
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_progress_excludes_synthetic_kps():
    """Regression: 全书导读/全书总结 (boundary kind) are read-only and
    never pass — _compute_progress must exclude them so the diary's
    completion reaches 100%, consistent with the course card and admin
    views (courses/router.py:214, admin/router.py:50)."""
    course_id, kp_id = await _setup_kp()
    try:
        async with SessionLocal() as db:
            kp = await db.get(KnowledgePoint, kp_id)
            kp.status = KPStatus.passed
            # A synthetic, never-passing companion KP in the same section.
            db.add(
                KnowledgePoint(
                    section_id=kp.section_id,
                    title="全书导读",
                    order_index=1,
                    boundary={"kind": "overview"},
                )
            )
            await db.commit()

        async with SessionLocal() as db:
            progress = await _compute_progress(course_id, db)
        # Synthetic KP must not drag the totals: 1/1 KP, 1/1 chapter.
        assert progress["kp_total"] == 1
        assert progress["kp_passed"] == 1
        assert progress["chapter_total"] == 1
        assert progress["chapter_passed"] == 1
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()


async def test_layer2_is_live_and_ignores_stale_snapshot():
    """ADR-0023: _build_layer2 always renders the live TeacherConfig.
    A stale KPMaterial.layer2_snapshot is ignored, and editing the
    persona mid-session is reflected on the very next call."""
    course_id, kp_id = await _setup_kp()
    try:
        async with SessionLocal() as db:
            db.add(
                TeacherConfig(
                    course_id=course_id,
                    scene="原始人物：耐心、温和",
                    learner_context="无",
                )
            )
            # Stale snapshot from the old frozen scheme — must be ignored.
            db.add(
                KPMaterial(
                    kp_id=kp_id,
                    layer3_prompt="lp",
                    keyphrases=["k"],
                    knowledge_checklist=[],
                    layer2_snapshot="SNAPSHOT-V1",
                )
            )
            await db.commit()

        async with SessionLocal() as db:
            layer2 = await _build_layer2(course_id, db)
        assert "SNAPSHOT-V1" not in layer2
        assert "原始人物" in layer2

        # mid-session persona edit → next call reflects it immediately
        async with SessionLocal() as db:
            cfg = await db.get(TeacherConfig, course_id)
            cfg.scene = "新人物：激进"
            await db.commit()

        async with SessionLocal() as db:
            layer2 = await _build_layer2(course_id, db)
        assert "新人物" in layer2
        assert "原始人物" not in layer2
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(Course).where(Course.id == course_id))
            await db.commit()
