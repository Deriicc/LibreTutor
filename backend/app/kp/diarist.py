"""Diarist — at KP end, the live persona writes a first-person,
in-character private diary entry for one (kp_id, attempt).

Mirrors the assessor/grader shape: pure render helpers (unit-testable
without DB/LLM) + a DB-aware orchestrator that owns its own session
and runs a pending→running→done/failed state machine.

The row is created `pending` by the orchestrator (so the book can show
a placeholder and the reaper can backfill failures), flipped to `done`
with body/signature/label, or `failed` with an error. Successful rows
are immutable — never regenerated. See ADR-0023 + CONTEXT.md.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.courses.report import _compute_progress
from app.courses.teacher_persona import render_persona_for_course
from app.db import SessionLocal
from app.llm import complete_json
from app.models import (
    Grade,
    KnowledgePoint,
    KPAssessment,
    KPStatus,
    Message,
    MessageRole,
    Submission,
    TeacherDiaryEntry,
    Weakness,
)
from app.user_llm import load_api_settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "teacher_diary.md"
DIARY_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


# ---------- LLM IO schema ----------


class _DiaryPayload(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)
    author_signature: str = Field(..., min_length=1, max_length=400)
    author_label: str = Field(..., min_length=1, max_length=64)


# ---------- pure render helpers ----------


def render_history_block(messages: list[Message]) -> str:
    lines: list[str] = []
    for m in messages:
        who = "学生" if m.role == MessageRole.user else "老师"
        lines.append(f"[{who}] {m.content}")
    return "\n".join(lines)


def render_prior_diary_block(
    entries: list[TeacherDiaryEntry], *, char_budget: int
) -> str:
    """Whole-book memory, newest-first until the char budget is hit, then
    re-ordered chronologically for the prompt. Oldest entries drop first
    so correctness never depends on the context window size."""
    if not entries:
        return "（这是这本日记的第一篇。）"

    chosen: list[TeacherDiaryEntry] = []
    used = 0
    for e in sorted(entries, key=lambda x: x.created_at, reverse=True):
        chunk = (e.body or "") + (e.author_signature or "")
        if chosen and used + len(chunk) > char_budget:
            break
        chosen.append(e)
        used += len(chunk)

    chosen.sort(key=lambda x: x.created_at)
    blocks: list[str] = []
    for e in chosen:
        when = e.created_at.strftime("%Y-%m-%d") if e.created_at else "?"
        label = e.author_label or "（未署名）"
        blocks.append(
            f"——【{when}·{label} 笔】——\n{e.body or ''}\n{e.author_signature or ''}"
        )
    return "\n\n".join(blocks)


def render_facts_block(
    *,
    kp_title: str,
    attempt: int,
    ended_by: str,
    kp_passed: bool,
    assessment: KPAssessment | None,
    grades: list[Grade],
    weaknesses: list[Weakness],
    progress: dict[str, Any],
) -> str:
    lines: list[str] = [
        f"知识点：{kp_title}",
        f"这是第 {attempt} 次教这一节"
        + ("（学生重做过）" if attempt > 1 else "（第一次）"),
        "这节怎么结束的："
        + (
            "学生选择继续下一节"
            if ended_by == "next"
            else "学生选择重做这一节"
        )
        + ("，且这一节已判定通过" if kp_passed else "，尚未通过/低分跳过"),
    ]
    if assessment is not None:
        covered = "、".join(c.get("concept", "") for c in (assessment.covered or []))
        partial = "、".join(p.get("concept", "") for p in (assessment.partial or []))
        untouched = "、".join(
            u.get("concept", "") for u in (assessment.untouched or [])
        )
        lines.append(
            f"对话覆盖评估：已掌握[{covered or '无'}]；"
            f"部分[{partial or '无'}]；未触及[{untouched or '无'}]；"
            f"覆盖度 {float(assessment.coverage_ratio):.0%}"
        )
        if assessment.mastery_summary:
            lines.append(f"评估小结：{assessment.mastery_summary}")
    else:
        lines.append("（这一节学生没有做评估/作业就走了）")

    if grades:
        for g in grades:
            per_q = "；".join(
                f"第{q.get('index', 0) + 1}题 {q.get('score', 0)}分"
                for q in (g.per_question or [])
            )
            lines.append(
                f"作业总分 {g.overall_score}/100。逐题：{per_q}。"
                f"老师评语：{g.overall_feedback}"
            )
    if weaknesses:
        wl = "；".join(w.description for w in weaknesses)
        lines.append(f"这个学生在本节累计的薄弱点：{wl}")

    lines.append(
        f"整体进度：已通过 {progress.get('kp_passed', 0)}/"
        f"{progress.get('kp_total', 0)} 个知识点，"
        f"{progress.get('chapter_passed', 0)}/{progress.get('chapter_total', 0)} 章，"
        f"累计学习约 {progress.get('study_minutes', 0)} 分钟"
    )
    return "\n".join(lines)


def build_diary_messages(
    *,
    persona_block: str,
    facts_block: str,
    history_block: str,
    prior_diary_block: str,
) -> list[dict[str, str]]:
    system = f"{DIARY_SYSTEM_PROMPT}\n\n# 你的角色\n\n{persona_block}"
    user = (
        f"# 这节课的真实材料\n\n{facts_block}\n\n"
        f"# 这节课你和学生的完整对话\n\n{history_block or '（没有对话记录）'}\n\n"
        f"# 你过往的日记（全文，按时间）\n\n{prior_diary_block}\n\n"
        f"现在，写下今天这一篇。严格按要求输出 JSON。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_diary_payload(raw: str) -> _DiaryPayload:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"日记响应不是合法 JSON：{exc}") from exc
    try:
        return _DiaryPayload.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"日记响应字段不合规：{exc}") from exc


# ---------- DB I/O ----------


async def _gather_inputs(
    kp_id: uuid.UUID, attempt: int, course_id: uuid.UUID, db: AsyncSession
) -> dict[str, Any]:
    kp = await db.get(KnowledgePoint, kp_id)
    kp_title = kp.title if kp is not None else "（未知知识点）"
    kp_passed = kp is not None and kp.status == KPStatus.passed

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.kp_id == kp_id, Message.attempt == attempt)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    assessment = await db.get(KPAssessment, (kp_id, attempt))

    grades = (
        await db.execute(
            select(Grade)
            .join(Submission, Submission.id == Grade.submission_id)
            .where(Submission.kp_id == kp_id, Submission.attempt == attempt)
            .order_by(Grade.created_at)
        )
    ).scalars().all()

    weaknesses = (
        await db.execute(
            select(Weakness)
            .where(Weakness.kp_id == kp_id, Weakness.course_id == course_id)
            .order_by(Weakness.created_at)
        )
    ).scalars().all()

    prior = (
        await db.execute(
            select(TeacherDiaryEntry).where(
                TeacherDiaryEntry.course_id == course_id,
                TeacherDiaryEntry.status == "done",
                ~(
                    (TeacherDiaryEntry.kp_id == kp_id)
                    & (TeacherDiaryEntry.attempt == attempt)
                ),
            )
        )
    ).scalars().all()

    progress = await _compute_progress(course_id, db)

    persona = await render_persona_for_course(course_id, db)

    return {
        "kp_title": kp_title,
        "kp_passed": kp_passed,
        "messages": list(msgs),
        "assessment": assessment,
        "grades": list(grades),
        "weaknesses": list(weaknesses),
        "prior": list(prior),
        "progress": progress,
        "persona": persona,
    }


async def _upsert_status(
    *,
    kp_id: uuid.UUID,
    attempt: int,
    course_id: uuid.UUID,
    status: str,
    ended_by: str,
    db: AsyncSession,
) -> None:
    values = {
        "kp_id": kp_id,
        "attempt": attempt,
        "course_id": course_id,
        "status": status,
        "ended_by": ended_by,
    }
    stmt = pg_insert(TeacherDiaryEntry).values(**values)
    # Don't clobber ended_by on re-entry (reaper re-runs keep the
    # original action recorded at first spawn).
    stmt = stmt.on_conflict_do_update(
        index_elements=["kp_id", "attempt"],
        set_={"status": status, "course_id": course_id},
    )
    await db.execute(stmt)
    await db.commit()


async def generate_diary_entry(
    kp_id: uuid.UUID,
    attempt: int,
    course_id: uuid.UUID,
    *,
    ended_by: str,
) -> None:
    """End-to-end diary generation for one (kp_id, attempt). Owns its own
    session. Idempotent on a `done` row: a successful entry is immutable
    and never overwritten (the reaper may re-invoke for pending/failed)."""
    async with SessionLocal() as db:
        existing = await db.get(TeacherDiaryEntry, (kp_id, attempt))
        if existing is not None and existing.status == "done":
            return  # immutable — never regenerate a written page

        await _upsert_status(
            kp_id=kp_id,
            attempt=attempt,
            course_id=course_id,
            status="running",
            ended_by=ended_by,
            db=db,
        )

        try:
            inputs = await _gather_inputs(kp_id, attempt, course_id, db)
            messages = build_diary_messages(
                persona_block=inputs["persona"],
                facts_block=render_facts_block(
                    kp_title=inputs["kp_title"],
                    attempt=attempt,
                    ended_by=ended_by,
                    kp_passed=inputs["kp_passed"],
                    assessment=inputs["assessment"],
                    grades=inputs["grades"],
                    weaknesses=inputs["weaknesses"],
                    progress=inputs["progress"],
                ),
                history_block=render_history_block(inputs["messages"]),
                prior_diary_block=render_prior_diary_block(
                    inputs["prior"],
                    char_budget=settings.diary_context_char_budget,
                ),
            )
            api_settings = await load_api_settings(db)
            raw = await complete_json(api_settings, messages)
            payload = parse_diary_payload(raw)

            row = await db.get(TeacherDiaryEntry, (kp_id, attempt))
            assert row is not None
            row.body = payload.body
            row.author_signature = payload.author_signature
            row.author_label = payload.author_label
            row.status = "done"
            row.error = None
            row.completed_at = datetime.now(tz=timezone.utc)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("generate_diary_entry failed for kp %s", kp_id)
            await db.rollback()
            failed = await db.get(TeacherDiaryEntry, (kp_id, attempt))
            if failed is not None and failed.status != "done":
                failed.status = "failed"
                failed.error = str(exc)[:1000]
                failed.completed_at = datetime.now(tz=timezone.utc)
                await db.commit()
            raise
