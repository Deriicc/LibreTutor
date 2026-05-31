import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from app.chat.router import router as chat_router
from app.config import settings
from app.courses.router import router as courses_router
from app.db import SessionLocal
from app.kp.diarist import generate_diary_entry
from app.kp.router import router as kp_router
from app.models import Submission, SubmissionStatus, TeacherDiaryEntry
from app.settings_router import router as settings_router

logger = logging.getLogger(__name__)


# How long a submission may sit in pending/running before the reaper
# assumes its grader task is dead. Five minutes is generous — a single
# LLM call rarely exceeds 30s.
STUCK_SUBMISSION_AGE = timedelta(minutes=5)
# Cadence for the in-process periodic reaper. Covers task crashes that
# don't take the whole worker down (so the boot reaper wouldn't fire).
REAPER_INTERVAL_SECONDS = 60


async def reset_inflight_submissions() -> int:
    """Mark any submission stuck in pending/running as failed.

    Why: graders run via in-process `asyncio.create_task`. Process restarts
    abandon those tasks, leaving rows wedged forever (PRD US 32). Sweep on
    boot so the user sees a clear "retry me" state instead of a hang.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            update(Submission)
            .where(
                Submission.status.in_(
                    [SubmissionStatus.pending, SubmissionStatus.running]
                )
            )
            .values(
                status=SubmissionStatus.failed,
                error="服务重启，原批阅未完成。请点击重做重新提交。",
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return result.rowcount or 0


async def reap_stuck_submissions() -> int:
    """Sweep submissions that have been in pending/running longer than
    STUCK_SUBMISSION_AGE. Catches the case where the worker stayed up
    but a single grader task crashed without flipping the status."""
    cutoff = datetime.now(timezone.utc) - STUCK_SUBMISSION_AGE
    async with SessionLocal() as db:
        result = await db.execute(
            update(Submission)
            .where(
                Submission.status.in_(
                    [SubmissionStatus.pending, SubmissionStatus.running]
                ),
                Submission.submitted_at < cutoff,
            )
            .values(
                status=SubmissionStatus.failed,
                error="批阅任务超时无响应。请点击重新批改重试。",
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return result.rowcount or 0


async def reap_pending_diary_entries() -> int:
    """Re-spawn teacher diary generation for entries stuck in
    pending/running/failed past STUCK_SUBMISSION_AGE. A diary failure
    leaves a hole in the chronological book *and* in the whole-book
    memory of every later entry, so we keep retrying until it lands.
    Successful (`done`) rows are immutable and never touched."""
    cutoff = datetime.now(timezone.utc) - STUCK_SUBMISSION_AGE
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(TeacherDiaryEntry).where(
                    TeacherDiaryEntry.status.in_(
                        ["pending", "running", "failed"]
                    ),
                    TeacherDiaryEntry.created_at < cutoff,
                )
            )
        ).scalars().all()
    for row in rows:
        kp_id, attempt, course_id, ended_by = (
            row.kp_id,
            row.attempt,
            row.course_id,
            row.ended_by,
        )

        async def _backfill(
            kp_id=kp_id,
            attempt=attempt,
            course_id=course_id,
            ended_by=ended_by,
        ) -> None:
            try:
                await generate_diary_entry(
                    kp_id, attempt, course_id, ended_by=ended_by
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "diary reaper backfill errored for kp %s attempt %s",
                    kp_id,
                    attempt,
                )

        asyncio.create_task(_backfill())
    return len(rows)


async def _periodic_reaper() -> None:
    while True:
        try:
            await asyncio.sleep(REAPER_INTERVAL_SECONDS)
            n = await reap_stuck_submissions()
            if n:
                logger.warning("periodic reaper: failed %s stuck submissions", n)
            d = await reap_pending_diary_entries()
            if d:
                logger.warning("periodic reaper: re-spawned %s diary entries", d)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("periodic reaper iteration errored")


@asynccontextmanager
async def lifespan(app: FastAPI):
    n = await reset_inflight_submissions()
    if n:
        logger.warning("startup: reset %s in-flight submissions to failed", n)

    reaper = asyncio.create_task(_periodic_reaper())
    try:
        yield
    finally:
        reaper.cancel()
        try:
            await reaper
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Self-Learning System",
    version="0.1.0",
    lifespan=lifespan,
    # Hide the interactive docs / schema in production — no need to
    # publish the full API surface to anonymous visitors.
    docs_url=None if settings.production else "/docs",
    redoc_url=None if settings.production else "/redoc",
    openapi_url=None if settings.production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses_router)
app.include_router(chat_router)
app.include_router(kp_router)
app.include_router(settings_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Static file serving (production only) ---
if settings.production:
    from starlette.staticfiles import StaticFiles

    _base = os.path.dirname(__file__)
    _static_student = os.path.join(_base, "..", "static", "student")
    if os.path.isdir(_static_student):
        app.mount("/", StaticFiles(directory=_static_student, html=True), name="student")
