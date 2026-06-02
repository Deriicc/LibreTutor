import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_session
from app.kp.assessor import run_assessment
from app.kp.decider import PASS_THRESHOLD, suggestion_for_score, upsert_weakness
from app.lang import lang_of
from app.kp.diarist import generate_diary_entry
from app.kp.grader import grade_submission
from app.kp.loader import get_kp_material
from app.kp.materializer import (
    materialize_kp_material,
    tailor_exercise_set,
)
from app.kp.schemas import (
    AdvanceIn,
    AdvanceOut,
    AssessmentOut,
    GradeOut,
    KPContentOut,
    SubmissionOut,
    SubmissionResultOut,
    SubmitIn,
)
from app.models import (
    Chapter,
    Course,
    Grade,
    KnowledgePoint,
    KPAssessment,
    KPExerciseSet,
    KPMaterial,
    KPStatus,
    Message,
    Section,
    Submission,
    SubmissionStatus,
    WeaknessSource,
)
from app.user_llm import load_api_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/courses/{course_id}/kp/{kp_id}", tags=["kp"])


async def _load_kp_with_course(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[Course, KnowledgePoint]:
    result = await db.execute(
        select(Course, KnowledgePoint)
        .join(Chapter, Chapter.course_id == Course.id)
        .join(Section, Section.chapter_id == Chapter.id)
        .join(KnowledgePoint, KnowledgePoint.section_id == Section.id)
        .where(
            KnowledgePoint.id == kp_id,
            Course.id == course_id,
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="knowledge point not found",
        )
    return row[0], row[1]


def _spawn_grader(submission_id: uuid.UUID) -> None:
    async def _run() -> None:
        try:
            await grade_submission(submission_id)
        except Exception:  # noqa: BLE001
            logger.exception("background grade_submission errored")

    asyncio.create_task(_run())


def _spawn_diarist(
    kp_id: uuid.UUID,
    attempt: int,
    course_id: uuid.UUID,
    *,
    ended_by: str,
) -> None:
    """Fire-and-forget the teacher diary for the attempt that just ended.
    Failures are swallowed — the periodic reaper backfills pending rows."""

    async def _run() -> None:
        try:
            await generate_diary_entry(
                kp_id, attempt, course_id, ended_by=ended_by
            )
        except Exception:  # noqa: BLE001
            logger.exception("background generate_diary_entry errored")

    asyncio.create_task(_run())


async def _attempt_has_activity(
    kp_id: uuid.UUID, attempt: int, db: AsyncSession
) -> bool:
    """A diary is only written when the attempt actually had teaching:
    ≥1 chat Message for the KP, or ≥1 Submission at this attempt."""
    msg = await db.execute(
        select(Message.id)
        .where(Message.kp_id == kp_id, Message.attempt == attempt)
        .limit(1)
    )
    if msg.first() is not None:
        return True
    sub = await db.execute(
        select(Submission.id)
        .where(Submission.kp_id == kp_id, Submission.attempt == attempt)
        .limit(1)
    )
    return sub.first() is not None


def _spawn_tailor(
    *,
    kp_id: uuid.UUID,
    attempt: int,
    kp_title: str,
    pdf_path: str,
    page_start: int,
    page_end: int,
    difficulty: str,
    count: int,
    api_settings: dict | None = None,
) -> None:
    """Background tailor: opens its own session and calls
    `tailor_exercise_set`. Failures are logged but swallowed — the
    lazy `/content` fallback regenerates on-demand."""

    async def _run() -> None:
        try:
            async with SessionLocal() as db:
                await tailor_exercise_set(
                    db,
                    kp_id=kp_id,
                    attempt=attempt,
                    kp_title=kp_title,
                    pdf_path=pdf_path,
                    page_start=page_start,
                    page_end=page_end,
                    difficulty=difficulty,
                    count=count,
                    api_settings=api_settings,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "background exercise-set tailor failed for kp %s", kp_id
            )

    asyncio.create_task(_run())


def _reject_synthetic_kp(kp: KnowledgePoint) -> None:
    """全书导读/全书总结 are read-only KPs — chat is allowed, but the
    assessment/exercise/pass loop is not. Block it defensively (the
    frontend already hides these affordances)."""
    if (kp.boundary or {}).get("kind"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="全书导读/全书总结为只读知识点，不参与练习与测评",
        )


def _kp_pages(kp: KnowledgePoint) -> tuple[int, int]:
    boundary = kp.boundary or {}
    ps = int(boundary.get("page_start") or 1)
    pe = int(boundary.get("page_end") or ps)
    return ps, pe


def _content_view(
    *, kp_id: uuid.UUID, material: KPMaterial, exercise_set: KPExerciseSet
) -> KPContentOut:
    return KPContentOut(
        kp_id=kp_id,
        layer3_prompt=material.layer3_prompt,
        keyphrases=list(material.keyphrases or []),
        exercises=list(exercise_set.exercises or []),
        difficulty=exercise_set.difficulty,
        count=exercise_set.count,
        created_at=exercise_set.created_at,
    )


@router.get("/content", response_model=KPContentOut)
async def get_kp_content(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> KPContentOut:
    """Return merged material + exercise set view.

    Material is generated by course-build prewarm; lazily filled here on
    rare cache misses (material has no params, so no key conflict).
    Exercise set must already exist — frontend calls POST /exercise-set
    before navigating to /exercise. Returns 404 if missing."""
    course, kp = await _load_kp_with_course(course_id, kp_id, db)
    page_start, page_end = _kp_pages(kp)

    material = await get_kp_material(db, kp_id)
    if material is None:
        try:
            material = await materialize_kp_material(
                db,
                course_id=course.id,
                kp_id=kp_id,
                kp_title=kp.title,
                pdf_path=course.source_pdf_path,
                page_start=page_start,
                page_end=page_end,
                api_settings=await load_api_settings(db),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    exercise_set = await db.get(KPExerciseSet, (kp_id, kp.current_attempt))
    if exercise_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="exercise set not ready; call POST /exercise-set first",
        )
    return _content_view(kp_id=kp_id, material=material, exercise_set=exercise_set)


async def _resolve_exercise_params(
    db: AsyncSession, *, kp_id: uuid.UUID
) -> tuple[str, int]:
    """Difficulty + count come from the latest KPAssessment for this KP.
    `attempt.desc()` so a freshly-retried attempt inherits the most recent
    assessment's suggestion until a new assessment is run. Falls back to
    ('normal', 5) when no assessment has been recorded yet."""
    q = await db.execute(
        select(KPAssessment)
        .where(KPAssessment.kp_id == kp_id)
        .order_by(KPAssessment.attempt.desc())
        .limit(1)
    )
    assessment = q.scalar_one_or_none()
    if assessment is None:
        return "normal", 5
    return assessment.suggested_difficulty, int(assessment.suggested_count)


@router.post("/exercise-set", response_model=KPContentOut)
async def post_exercise_set(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> KPContentOut:
    """Generate (or return cached) exercise set for the current attempt.
    Difficulty + count are drawn from the latest KPAssessment — the
    student doesn't pick them. Short-circuits when the cached row
    already matches assessor suggestions, so the post-assessment
    background tailor's work isn't wasted.

    Always returns the full KPContentOut so the caller can navigate
    straight to /exercise without a follow-up GET."""
    course, kp = await _load_kp_with_course(course_id, kp_id, db)
    _reject_synthetic_kp(kp)
    page_start, page_end = _kp_pages(kp)
    api_settings = await load_api_settings(db)

    material = await get_kp_material(db, kp_id)
    if material is None:
        try:
            material = await materialize_kp_material(
                db,
                course_id=course.id,
                kp_id=kp_id,
                kp_title=kp.title,
                pdf_path=course.source_pdf_path,
                page_start=page_start,
                page_end=page_end,
                api_settings=api_settings,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    difficulty, count = await _resolve_exercise_params(db, kp_id=kp_id)

    exercise_set = await db.get(KPExerciseSet, (kp_id, kp.current_attempt))
    if (
        exercise_set is not None
        and exercise_set.difficulty == difficulty
        and exercise_set.count == count
    ):
        return _content_view(
            kp_id=kp_id, material=material, exercise_set=exercise_set
        )

    try:
        exercise_set = await tailor_exercise_set(
            db,
            kp_id=kp_id,
            attempt=kp.current_attempt,
            kp_title=kp.title,
            pdf_path=course.source_pdf_path,
            page_start=page_start,
            page_end=page_end,
            difficulty=difficulty,
            count=count,
            api_settings=api_settings,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if exercise_set is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="KP material disappeared mid-request",
        )
    return _content_view(kp_id=kp_id, material=material, exercise_set=exercise_set)


@router.post(
    "/submissions",
    response_model=SubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_answers(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    payload: SubmitIn,
    db: AsyncSession = Depends(get_session),
) -> Submission:
    _, kp = await _load_kp_with_course(course_id, kp_id, db)
    _reject_synthetic_kp(kp)
    exercise_set = await db.get(KPExerciseSet, (kp_id, kp.current_attempt))
    if exercise_set is not None and len(payload.answers) != len(exercise_set.exercises):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"answers count ({len(payload.answers)}) does not match "
                f"exercise set size ({len(exercise_set.exercises)})"
            ),
        )
    submission = Submission(
        kp_id=kp_id,
        attempt=kp.current_attempt,
        answers=[a.model_dump() for a in payload.answers],
        status=SubmissionStatus.pending,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    _spawn_grader(submission.id)
    return submission


@router.get(
    "/submissions/{submission_id}",
    response_model=SubmissionResultOut,
)
async def get_submission(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> SubmissionResultOut:
    await _load_kp_with_course(course_id, kp_id, db)

    submission = await db.get(Submission, submission_id)
    if submission is None or submission.kp_id != kp_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="submission not found",
        )

    grade_row = await db.get(Grade, submission_id)
    grade_payload = GradeOut.model_validate(grade_row) if grade_row else None
    suggestion = (
        suggestion_for_score(
            grade_row.overall_score, lang_of(await load_api_settings(db))
        )
        if grade_row is not None
        else None
    )

    return SubmissionResultOut(
        submission=SubmissionOut.model_validate(submission),
        grade=grade_payload,
        suggestion=suggestion,
    )


@router.post(
    "/submissions/{submission_id}/regrade",
    response_model=SubmissionOut,
)
async def regrade_submission(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> Submission:
    """Re-queue a failed submission for grading. Only allowed when the
    submission's current status is `failed` — successful grades are not
    re-runnable to avoid unintended score changes."""
    await _load_kp_with_course(course_id, kp_id, db)
    submission = await db.get(Submission, submission_id)
    if submission is None or submission.kp_id != kp_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="submission not found",
        )
    if submission.status != SubmissionStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"only failed submissions can be regraded (current: {submission.status})",
        )
    submission.status = SubmissionStatus.pending
    submission.error = None
    submission.completed_at = None
    await db.commit()
    await db.refresh(submission)
    _spawn_grader(submission.id)
    return submission


async def _last_done_grade(
    kp_id: uuid.UUID, db: AsyncSession
) -> Grade | None:
    sub_q = await db.execute(
        select(Submission)
        .where(
            Submission.kp_id == kp_id,
            Submission.status == SubmissionStatus.done,
        )
        .order_by(Submission.completed_at.desc())
        .limit(1)
    )
    last_sub = sub_q.scalar_one_or_none()
    if last_sub is None:
        return None
    return await db.get(Grade, last_sub.id)


@router.post("/assessment", response_model=AssessmentOut)
async def post_assessment(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> AssessmentOut:
    """Compute and persist a KPAssessment for the current attempt.
    Re-running on the same attempt overwrites the prior snapshot.

    On success, fires a background task to tailor the exercise set with
    dialogue-derived covered_concepts so the student gets a cache hit on
    the next /content request."""
    course, kp = await _load_kp_with_course(course_id, kp_id, db)
    _reject_synthetic_kp(kp)
    api_settings = await load_api_settings(db)
    try:
        row = await run_assessment(
            kp_id=kp_id,
            attempt=kp.current_attempt,
            db=db,
            api_settings=api_settings,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"评估失败：{exc}",
        ) from exc

    if row.covered or row.partial:
        page_start, page_end = _kp_pages(kp)
        _spawn_tailor(
            kp_id=kp_id,
            attempt=kp.current_attempt,
            kp_title=kp.title,
            pdf_path=course.source_pdf_path,
            page_start=page_start,
            page_end=page_end,
            difficulty=row.suggested_difficulty,
            count=row.suggested_count,
            api_settings=api_settings,
        )

    return AssessmentOut.model_validate(row)


@router.post("/advance", response_model=AdvanceOut)
async def advance(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    payload: AdvanceIn,
    db: AsyncSession = Depends(get_session),
) -> AdvanceOut:
    course, kp = await _load_kp_with_course(course_id, kp_id, db)
    _reject_synthetic_kp(kp)

    if payload.action == "retry":
        # The attempt that is ending is the current one — capture it
        # before the bump so the diary is keyed to the right attempt.
        ending_attempt = kp.current_attempt
        if await _attempt_has_activity(kp_id, ending_attempt, db):
            _spawn_diarist(
                kp_id, ending_attempt, course.id, ended_by="retry"
            )
        # Bump current_attempt so the next /content regenerates a fresh
        # exercise set at the new attempt. Past exercise sets stay so the
        # report can render historical submissions.
        kp.current_attempt += 1
        await db.commit()
        return AdvanceOut(action="retry", kp_status=kp.status)

    # action == "next"
    last_grade = await _last_done_grade(kp_id, db)
    if last_grade is not None and last_grade.overall_score < PASS_THRESHOLD:
        await upsert_weakness(
            db,
            course_id=course.id,
            kp_id=kp.id,
            source=WeaknessSource.skipped,
            description=(
                f"用户跳过未掌握的知识点（{last_grade.overall_score}/100）"
            ),
        )
    ending_attempt = kp.current_attempt
    kp.status = KPStatus.passed
    await db.commit()
    if await _attempt_has_activity(kp_id, ending_attempt, db):
        _spawn_diarist(kp_id, ending_attempt, course.id, ended_by="next")
    return AdvanceOut(action="next", kp_status=kp.status)
