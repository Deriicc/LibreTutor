"""Assessor — read a chat history + knowledge_checklist, return a coverage/
mastery snapshot via one LLM call.

Output is persisted to KPAssessment keyed by (kp_id, attempt). Re-running
assessment on the same attempt UPSERTS the row (latest snapshot wins).

The pure functions (render_history_block, build_assessment_messages,
parse_and_validate_payload) are unit-testable without a DB or an LLM.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_json
from app.models import KnowledgePoint, KPAssessment, KPMaterial, Message, MessageRole

logger = logging.getLogger(__name__)


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "assessment.md"
ASSESSMENT_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


# ---------- LLM IO schema ----------


Difficulty = Literal["easy", "normal", "hard"]


class _CoveredItem(BaseModel):
    concept: str = Field(..., min_length=1)
    evidence: str = Field(..., min_length=1)


class _PartialItem(BaseModel):
    concept: str = Field(..., min_length=1)
    evidence: str = Field(..., min_length=1)


class _UntouchedItem(BaseModel):
    concept: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class AssessmentPayload(BaseModel):
    """LLM-produced assessment for one KP."""

    covered: list[_CoveredItem]
    partial: list[_PartialItem]
    untouched: list[_UntouchedItem]
    coverage_ratio: float = Field(..., ge=0.0, le=1.0)
    mastery_summary: str = Field(..., min_length=1, max_length=400)
    suggested_difficulty: Difficulty
    suggested_count: int = Field(..., ge=2, le=7)

    @field_validator("coverage_ratio")
    @classmethod
    def _round_two_decimals(cls, v: float) -> float:
        return round(v, 2)


# ---------- Pure helpers ----------


def render_history_block(history: list[Message]) -> str:
    """Pure: render messages as `[student]: ...` / `[teacher]: ...` lines.
    Empty history → empty string (caller decides how to fall back)."""
    lines: list[str] = []
    for m in history:
        prefix = "[student]" if m.role == MessageRole.user else "[teacher]"
        lines.append(f"{prefix}: {m.content}")
    return "\n".join(lines)


def render_checklist_for_assessor(checklist: list[dict[str, Any]] | None) -> str:
    """Pure: render the KP's knowledge_checklist into the assessor prompt.

    Concept names are kept clean (no leading marker characters) so the LLM
    can echo them back verbatim into the JSON output. The must_anchor flag
    is communicated as a trailing tag, not a prefix character — earlier
    versions used '★ {concept}' which the LLM faithfully copied into its
    JSON, breaking strict concept-set matching."""
    if not checklist:
        return ""
    lines: list[str] = []
    for item in checklist:
        concept = item.get("concept", "")
        desc = item.get("description", "")
        anchor_tag = "  [必须锚定]" if item.get("must_anchor") else ""
        lines.append(f"- {concept}：{desc}{anchor_tag}")
    return "\n".join(lines)


def build_assessment_messages(
    *,
    kp_title: str,
    checklist_block: str,
    history_block: str,
) -> list[dict[str, str]]:
    """Pure: assemble the system+user message pair for the assessor LLM."""
    user_content = (
        f"# 知识点\n\n{kp_title}\n\n"
        f"# 知识清单\n\n{checklist_block}\n\n"
        f"# 对话历史\n\n{history_block}"
    )
    return [
        {"role": "system", "content": ASSESSMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_and_validate_payload(
    raw: str, *, expected_concepts: list[str]
) -> AssessmentPayload:
    """Pure: parse LLM JSON, run pydantic validation, then enforce that
    every checklist concept appears exactly once across covered/partial/
    untouched. Raises ValueError if anything is off."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"评估响应不是合法 JSON：{exc}") from exc

    # Defensive normalization: some LLMs faithfully copy markers like '★ '
    # from the input checklist into the output concept string. Strip a few
    # known prefix characters so cross-set matching works.
    def _normalize(s: str) -> str:
        return s.strip().lstrip("★ ").strip()

    for bucket in ("covered", "partial", "untouched"):
        items = data.get(bucket, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "concept" in item:
                    item["concept"] = _normalize(item["concept"])

    try:
        payload = AssessmentPayload.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"评估响应字段不合规：{exc}") from exc

    seen: dict[str, str] = {}  # concept -> bucket name
    for bucket_name, items in (
        ("covered", payload.covered),
        ("partial", payload.partial),
        ("untouched", payload.untouched),
    ):
        for item in items:
            if item.concept in seen:
                raise ValueError(
                    f"概念「{item.concept}」在 {seen[item.concept]} 和 "
                    f"{bucket_name} 中重复出现"
                )
            seen[item.concept] = bucket_name

    expected_set = set(expected_concepts)
    seen_set = set(seen.keys())
    missing = expected_set - seen_set
    extra = seen_set - expected_set
    if missing:
        raise ValueError(f"评估漏掉了清单概念：{sorted(missing)}")
    if extra:
        raise ValueError(f"评估包含清单外概念：{sorted(extra)}")

    return payload


# ---------- DB I/O ----------


def _empty_assessment(attempt: int) -> AssessmentPayload:
    """Fallback when there's nothing to assess (no chat history / no checklist).
    Surfaces as 0% coverage, easy/2-question default — UI can react sensibly."""
    return AssessmentPayload(
        covered=[],
        partial=[],
        untouched=[],
        coverage_ratio=0.0,
        mastery_summary="对话尚未开始或没有内容可评估，建议先回去和老师讨论后再来作业。",
        suggested_difficulty="easy",
        suggested_count=2,
    )


async def _load_history(
    kp_id: uuid.UUID, attempt: int, db: AsyncSession
) -> list[Message]:
    """Only this attempt's dialogue — a retried round must be assessed on
    its own conversation, not polluted by the round it replaced."""
    result = await db.execute(
        select(Message)
        .where(Message.kp_id == kp_id, Message.attempt == attempt)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def _upsert_assessment(
    *,
    kp_id: uuid.UUID,
    attempt: int,
    payload: AssessmentPayload,
    db: AsyncSession,
) -> KPAssessment:
    """ON CONFLICT (kp_id, attempt) DO UPDATE — re-running assessment on the
    same attempt replaces the prior snapshot."""
    values = {
        "kp_id": kp_id,
        "attempt": attempt,
        "covered": [item.model_dump() for item in payload.covered],
        "partial": [item.model_dump() for item in payload.partial],
        "untouched": [item.model_dump() for item in payload.untouched],
        "coverage_ratio": payload.coverage_ratio,
        "mastery_summary": payload.mastery_summary,
        "suggested_difficulty": payload.suggested_difficulty,
        "suggested_count": payload.suggested_count,
    }
    stmt = pg_insert(KPAssessment).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kp_id", "attempt"],
        set_={k: v for k, v in values.items() if k not in ("kp_id", "attempt")},
    )
    await db.execute(stmt)
    await db.commit()

    row = await db.get(KPAssessment, (kp_id, attempt))
    assert row is not None  # we just inserted/updated it
    return row


async def run_assessment(
    *,
    kp_id: uuid.UUID,
    attempt: int,
    db: AsyncSession,
    api_settings: dict | None = None,
) -> KPAssessment:
    """Compute and persist a KPAssessment for the given (kp_id, attempt).

    - Empty checklist or empty history → store the empty fallback (no LLM call)
    - Otherwise → call the assessor LLM, validate, upsert
    """
    kp = await db.get(KnowledgePoint, kp_id)
    if kp is None:
        raise ValueError(f"KP {kp_id} not found")

    material = await db.get(KPMaterial, kp_id)
    checklist = material.knowledge_checklist if material is not None else []

    history = await _load_history(kp_id, attempt, db)

    if not checklist or not history:
        payload = _empty_assessment(attempt)
        return await _upsert_assessment(
            kp_id=kp_id, attempt=attempt, payload=payload, db=db
        )

    expected_concepts = [item["concept"] for item in checklist]
    messages = build_assessment_messages(
        kp_title=kp.title,
        checklist_block=render_checklist_for_assessor(checklist),
        history_block=render_history_block(history),
    )

    raw = await complete_json(api_settings, messages)
    payload = parse_and_validate_payload(raw, expected_concepts=expected_concepts)

    return await _upsert_assessment(
        kp_id=kp_id, attempt=attempt, payload=payload, db=db
    )
