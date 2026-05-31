"""KP write-side: generate + persist KPMaterial and KPExerciseSet.

Two LLM-driven generators, two UPSERT-style materializers, plus a
tailor orchestrator that gathers covered_concepts from the latest
assessor output and writes the exercise set in one call.

Schemas and validators live in `exercise_validators`; layout helpers
in `exercise_layout`. This module is the IO + LLM call site only.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.kp.exercise_layout import COUNT_RANGE, layout, scaled_difficulty_mix
from app.kp.exercise_validators import (
    ExerciseSetPayload,
    KPMaterialPayload,
    validate_difficulty_types,
    validate_layout,
    validate_self_contained,
    validate_topic_whitelist,
)
from app.kp.loader import extract_kp_text
from app.llm import complete_json
from app.models import (
    KPAssessment,
    KPExerciseSet,
    KPMaterial,
)

logger = logging.getLogger(__name__)


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
KP_MATERIAL_SYSTEM_PROMPT = (_PROMPTS_DIR / "kp_material.md").read_text(encoding="utf-8")
EXERCISE_SET_SYSTEM_PROMPT = (_PROMPTS_DIR / "exercise_set.md").read_text(encoding="utf-8")
BOOK_OVERVIEW_SYSTEM_PROMPT = (_PROMPTS_DIR / "book_overview.md").read_text(
    encoding="utf-8"
)


# ---------- LLM generators ----------


async def generate_kp_material(
    kp_title: str,
    pdf_path: str,
    page_start: int,
    page_end: int,
    *,
    api_settings: dict | None = None,
    max_retries: int = 1,
) -> KPMaterialPayload:
    """Generate teaching material for a KP from its PDF text slice.

    Pure: no DB. Caller persists via `materialize_kp_material`.
    """
    text = extract_kp_text(pdf_path, page_start, page_end)
    if not text.strip():
        raise ValueError(
            f"无法从 PDF 抽取页 {page_start}-{page_end} 的文本（可能是图片型 PDF）"
        )

    user_msg = (
        f"知识点：{kp_title}\n"
        f"PDF 页码：{page_start} - {page_end}\n\n"
        f"文本内容：\n{text}"
    )
    messages = [
        {"role": "system", "content": KP_MATERIAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = await complete_json(api_settings, messages)
            data = json.loads(raw)
            return KPMaterialPayload.model_validate(data)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_err = exc
            logger.warning(
                "KP material generation failed (attempt %s/%s) for kp_title=%r: %s",
                attempt + 1,
                max_retries + 1,
                kp_title,
                exc,
            )
            continue
    raise ValueError(f"KP 教学物料生成失败：{last_err}")


async def generate_book_overview_material(
    *,
    kind: str,
    outline_text: str,
    matter_text: str,
    api_settings: dict | None = None,
    max_retries: int = 1,
) -> KPMaterialPayload:
    """Generate the book-level 全书导读/全书总结 material from the whole-book
    outline + front/back-matter text (never a KP page slice).

    Reuses ``KPMaterialPayload`` so the same chat layer consumes it. Pure:
    no DB. Caller persists via ``materialize_book_overview_material``.
    """
    label = "overview（全书导读）" if kind == "overview" else "summary（全书总结）"
    user_msg = (
        f"类型：{label}\n\n"
        f"全书章节大纲：\n{outline_text}\n\n"
        f"辅文原文：\n{matter_text or '（本书无可用序言/结语，请仅依据大纲生成）'}"
    )
    messages = [
        {"role": "system", "content": BOOK_OVERVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = await complete_json(api_settings, messages)
            data = json.loads(raw)
            return KPMaterialPayload.model_validate(data)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_err = exc
            logger.warning(
                "book overview material generation failed (attempt %s/%s) "
                "kind=%r: %s",
                attempt + 1,
                max_retries + 1,
                kind,
                exc,
            )
            continue
    raise ValueError(f"全书导读/总结物料生成失败：{last_err}")


async def generate_exercise_set(
    kp_title: str,
    pdf_path: str,
    page_start: int,
    page_end: int,
    *,
    keyphrases: list[str],
    covered_concepts: list[str] | None = None,
    difficulty: str = "normal",
    count: int = 5,
    api_settings: dict | None = None,
    max_retries: int = 1,
) -> ExerciseSetPayload:
    """Generate exercises tailored to dialogue covered_concepts.

    `keyphrases` come from the KPMaterial — they orient the LLM toward
    the KP's terminology. `covered_concepts` is the hard topic
    whitelist; the validator enforces each question's stem contains at
    least one whitelist concept.
    """
    if difficulty not in {"easy", "normal", "hard"}:
        raise ValueError(
            f"difficulty must be one of easy/normal/hard, got {difficulty!r}"
        )
    lo, hi = COUNT_RANGE
    if count < lo or count > hi:
        raise ValueError(f"count must be in [{lo}, {hi}], got {count}")

    text = extract_kp_text(pdf_path, page_start, page_end)
    if not text.strip():
        raise ValueError(
            f"无法从 PDF 抽取页 {page_start}-{page_end} 的文本（可能是图片型 PDF）"
        )

    seq = layout(count)
    n_mcq = sum(1 for t in seq if t == "mcq")
    n_short = sum(1 for t in seq if t == "short_answer")

    base_user_msg = (
        f"知识点：{kp_title}\n"
        f"PDF 页码：{page_start} - {page_end}\n"
        f"关键词（命题锚点）：{'、'.join(keyphrases)}\n\n"
        f"文本内容：\n{text}"
    )
    extras: list[str] = []

    extras.append(
        f"题量与布局：本次共 {count} 道题，其中 mcq {n_mcq} 道在前，"
        f"short_answer {n_short} 道在后。"
    )

    if covered_concepts:
        concepts_str = "、".join(f"「{c}」" for c in covered_concepts)
        extras.append(
            f"考察范围（硬约束）：本次作业的所有题目**必须**只考察以下概念，"
            f"禁止考察列表外的内容。每道题在题干中必须明确提及至少一个列表概念。\n"
            f"概念列表：{concepts_str}"
        )
    if difficulty != "normal":
        scaled = scaled_difficulty_mix(difficulty, count)
        mcq_types = "、".join(scaled["mcq"])
        short_types = "、".join(scaled["short_answer"])
        extras.append(
            f"难度档：{difficulty}\n"
            f"本次出题题型必须严格按以下分布：\n"
            f"- {n_mcq} 道 mcq 题型依次为：{mcq_types}\n"
            f"- {n_short} 道 short_answer 题型依次为：{short_types}"
        )

    user_msg = base_user_msg
    if extras:
        user_msg = base_user_msg + "\n\n" + "\n\n".join(extras)

    messages = [
        {"role": "system", "content": EXERCISE_SET_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = await complete_json(api_settings, messages)
            data = json.loads(raw)
            parsed = ExerciseSetPayload.model_validate(data)
            validate_layout(
                parsed.exercises,
                count=count,
                difficulty=difficulty,
            )
            validate_difficulty_types(
                parsed.exercises,
                difficulty=difficulty,
                count=count,
            )
            validate_self_contained(parsed.exercises)
            if covered_concepts:
                validate_topic_whitelist(
                    parsed.exercises,
                    covered_concepts=covered_concepts,
                )
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_err = exc
            logger.warning(
                "Exercise set generation failed (attempt %s/%s) for kp_title=%r: %s",
                attempt + 1,
                max_retries + 1,
                kp_title,
                exc,
            )
            continue
    raise ValueError(f"练习集生成失败：{last_err}")


# ---------- Materializers (persist) ----------


async def _upsert_kp_material(
    db: AsyncSession, kp_id: uuid.UUID, payload: KPMaterialPayload
) -> KPMaterial:
    values = {
        "kp_id": kp_id,
        "layer3_prompt": payload.layer3_prompt,
        "keyphrases": payload.keyphrases,
        "knowledge_checklist": [item.model_dump() for item in payload.knowledge_checklist],
    }
    stmt = pg_insert(KPMaterial).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kp_id"],
        set_={k: v for k, v in values.items() if k != "kp_id"},
    )
    await db.execute(stmt)
    await db.commit()

    row = await db.get(KPMaterial, kp_id)
    assert row is not None
    return row


async def materialize_kp_material(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    kp_title: str,
    pdf_path: str,
    page_start: int,
    page_end: int,
    api_settings: dict | None = None,
) -> KPMaterial:
    """Generate + UPSERT KPMaterial for a KP.

    Persona is no longer snapshotted here — chat renders the live
    TeacherConfig persona every turn (ADR-0023, supersedes ADR-0020).
    `KPMaterial.layer2_snapshot` is left unwritten (deprecated column).
    `course_id` is retained for caller stability / future use.
    """
    payload = await generate_kp_material(
        kp_title=kp_title,
        pdf_path=pdf_path,
        page_start=page_start,
        page_end=page_end,
        api_settings=api_settings,
    )
    return await _upsert_kp_material(db, kp_id, payload)


async def materialize_book_overview_material(
    db: AsyncSession,
    *,
    kp_id: uuid.UUID,
    kind: str,
    outline_text: str,
    matter_text: str,
    api_settings: dict | None = None,
) -> KPMaterial:
    """Generate + UPSERT KPMaterial for a synthetic 全书导读/全书总结 KP.

    Same KPMaterial shape as a normal KP (so chat consumes it
    unchanged), but synthesized from the whole-book outline + matter
    text instead of a KP page slice.
    """
    payload = await generate_book_overview_material(
        kind=kind,
        outline_text=outline_text,
        matter_text=matter_text,
        api_settings=api_settings,
    )
    return await _upsert_kp_material(db, kp_id, payload)


def _merge_topic_whitelist(
    covered_concepts: list[str] | None, keyphrases: list[str]
) -> list[str] | None:
    """Combine assessor-derived concepts with material keyphrases.

    Concepts can be multi-word ("可导与连续") while LLM-generated
    questions often use the shorter keyphrase form ("可导"); merging
    both lets the topic whitelist substring check pass for either form.

    Returns None when both inputs are empty/None.
    """
    merged: list[str] = list(covered_concepts) if covered_concepts else []
    merged.extend(keyphrases or [])
    merged = [c for c in merged if c]
    seen: set[str] = set()
    deduped: list[str] = []
    for c in merged:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    if not deduped:
        return None
    return deduped


async def materialize_kp_exercise_set(
    db: AsyncSession,
    *,
    kp_id: uuid.UUID,
    attempt: int,
    kp_title: str,
    pdf_path: str,
    page_start: int,
    page_end: int,
    material: KPMaterial,
    covered_concepts: list[str] | None = None,
    difficulty: str = "normal",
    count: int = 5,
    api_settings: dict | None = None,
) -> KPExerciseSet:
    """Generate + INSERT KPExerciseSet for a (kp_id, attempt).

    Write-once per (kp_id, attempt): if a set already exists it is
    returned unchanged — never regenerated or overwritten. A retry bumps
    `KnowledgePoint.current_attempt`, so the next round naturally gets a
    fresh row at the new attempt. This guarantees a Submission is always
    graded against the exact questions the student answered: any later
    generation (background `_spawn_tailor`, or a param-change
    `POST /exercise-set`) must not swap the questions under a student who
    already rendered them.

    `covered_concepts` (assessor-derived) is merged with
    `material.keyphrases` internally to form the topic whitelist.
    """
    existing = await db.get(KPExerciseSet, (kp_id, attempt))
    if existing is not None:
        return existing

    effective_whitelist = _merge_topic_whitelist(
        covered_concepts, material.keyphrases or []
    )
    payload = await generate_exercise_set(
        kp_title=kp_title,
        pdf_path=pdf_path,
        page_start=page_start,
        page_end=page_end,
        keyphrases=material.keyphrases or [],
        covered_concepts=effective_whitelist,
        difficulty=difficulty,
        count=count,
        api_settings=api_settings,
    )

    values = {
        "kp_id": kp_id,
        "attempt": attempt,
        "exercises": [e.model_dump(mode="json") for e in payload.exercises],
        "difficulty": difficulty,
        "count": count,
    }
    stmt = pg_insert(KPExerciseSet).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kp_id", "attempt"],
        set_={k: v for k, v in values.items() if k not in ("kp_id", "attempt")},
    )
    await db.execute(stmt)
    await db.commit()

    row = await db.get(KPExerciseSet, (kp_id, attempt))
    assert row is not None
    return row


# ---------- Tailor inputs (formerly inline in kp/router.py) ----------


async def derive_covered_concepts(
    db: AsyncSession, kp_id: uuid.UUID
) -> list[str] | None:
    """Pull concept names from the latest KPAssessment for this KP
    (covered + partial). Returns None when nothing is available."""
    q = await db.execute(
        select(KPAssessment)
        .where(KPAssessment.kp_id == kp_id)
        .order_by(KPAssessment.attempt.desc())
        .limit(1)
    )
    assessment = q.scalar_one_or_none()
    if assessment is None:
        return None
    concepts = [
        *(c.get("concept") for c in (assessment.covered or [])),
        *(p.get("concept") for p in (assessment.partial or [])),
    ]
    concepts = [c for c in concepts if c]
    return concepts or None


async def tailor_exercise_set(
    db: AsyncSession,
    *,
    kp_id: uuid.UUID,
    attempt: int,
    kp_title: str,
    pdf_path: str,
    page_start: int,
    page_end: int,
    difficulty: str = "normal",
    count: int = 5,
    api_settings: dict | None = None,
) -> KPExerciseSet | None:
    """End-to-end: gather covered_concepts from prior assessor output,
    then materialize the exercise set. Returns None when no KPMaterial
    exists yet (caller should fall back to lazy materialize_kp_material).
    """
    material = await db.get(KPMaterial, kp_id)
    if material is None:
        return None
    covered_concepts = await derive_covered_concepts(db, kp_id)
    return await materialize_kp_exercise_set(
        db,
        kp_id=kp_id,
        attempt=attempt,
        kp_title=kp_title,
        pdf_path=pdf_path,
        page_start=page_start,
        page_end=page_end,
        material=material,
        covered_concepts=covered_concepts,
        difficulty=difficulty,
        count=count,
        api_settings=api_settings,
    )
