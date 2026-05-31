"""Chat three-layer system prompt assembly.

Layer 1 (hard-coded, file-backed): pure Socratic teaching rules + meta
instructions telling the model to roleplay the Layer 2 scene.
Layer 2 (TeacherConfig persona): rendered by `app.courses.teacher_persona`.
Layer 3 (per-KP): teaching hint from KPMaterial + course position (where
this KP sits, what came before, what's next) from `app.courses.progress`.

Beyond turn 20 we append a directive forcing the LLM to ask the student
whether they want to move on to the exercise page.

This module owns pure prompt rendering + the orchestration that pulls
all three layers together. Course-domain queries live in
`app.courses.progress` and `app.courses.teacher_persona`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.courses.progress import get_kp_position
from app.courses.teacher_persona import render_persona_for_course
from app.models import Message, MessageRole


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
LAYER1_PROMPT = (_PROMPTS_DIR / "socratic_layer1.md").read_text(encoding="utf-8")


SOFT_TURN_CAP = 20

DIALOGUE_TEMPERATURE = 0.8


def count_turns(messages: list[Message]) -> int:
    """A turn = one user-sent message. Counts user messages in history."""
    return sum(1 for m in messages if m.role == MessageRole.user)


async def _build_layer3(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    kp_title: str,
    db: AsyncSession,
) -> str:
    from app.kp.loader import get_kp_material

    pos, prev, nxt = await get_kp_position(course_id, kp_id, db)
    material = await get_kp_material(db, kp_id)
    teaching_hint = (
        material.layer3_prompt
        if material is not None
        else "（暂无教材切入点，基于学生回答自行推进；不引入文本外内容）"
    )
    keyphrases = (
        "、".join(material.keyphrases)
        if material is not None and material.keyphrases
        else "（无）"
    )

    prev_str = "、".join(prev) if prev else "（这是第一个知识点）"
    next_str = "、".join(nxt) if nxt else "（这是最后一个知识点）"

    checklist_block = render_checklist_block(
        material.knowledge_checklist if material is not None else []
    )

    base = (
        f"当前学习上下文：\n"
        f"- 你正在教第 {pos} 个知识点：「{kp_title}」\n"
        f"- 学生之前学过：{prev_str}\n"
        f"- 接下来还要学：{next_str}\n"
        f"- 该 KP 的核心关键词：{keyphrases}\n"
        f"\n"
        f"KP 教学切入点：{teaching_hint}"
    )
    if checklist_block:
        return f"{base}\n\n{checklist_block}"
    return base


def render_checklist_block(checklist: list[dict] | None) -> str:
    """Pure: render a knowledge_checklist (list of {concept, description,
    must_anchor}) into a Layer 3 addendum. Returns "" when empty.

    must_anchor items get a leading "★" so the dialogue LLM treats it as
    typography, not as part of the concept name."""
    if not checklist:
        return ""
    lines = [
        "该 KP 必须覆盖的知识清单（请确保对话中逐一覆盖；标记 ★ 的概念**必须**经过锚定阶段）："
    ]
    for item in checklist:
        concept = item.get("concept", "")
        desc = item.get("description", "")
        marker = "★ " if item.get("must_anchor") else "  "
        lines.append(f"{marker}「{concept}」：{desc}")
    return "\n".join(lines)


def _soft_cap_directive(turn_count: int) -> str:
    return (
        f"对话已进行 {turn_count} 轮，达到 {SOFT_TURN_CAP} 轮上限。"
        f"本轮**必须**主动询问学生：「要不要进作业？」并提供 3 个选项："
        f"1. 继续学习  2. 进作业页做练习  3. 休息一下。"
    )


def render_retrieval_block(chunks: list[str]) -> str:
    """Pure: format retrieved PDF excerpts as a Layer 3 addendum."""
    if not chunks:
        return ""
    lines = ["该知识点的教材原文（请基于以下内容进行教学，不引入文本外的内容）："]
    for i, c in enumerate(chunks, 1):
        lines.append(f"[片段 {i}] {c}")
    return "\n".join(lines)


def assemble_system_prompt(layer2: str, layer3: str, turn_count: int) -> str:
    """Pure assembly of the three layers + optional soft-cap directive."""
    parts = [LAYER1_PROMPT, layer2, layer3]
    if turn_count >= SOFT_TURN_CAP:
        parts.append(_soft_cap_directive(turn_count))
    return "\n\n".join(parts)


async def _build_layer2(course_id: uuid.UUID, db: AsyncSession) -> str:
    """Always render the live TeacherConfig persona. Persona edits take
    effect on the next turn — including mid-conversation — which is the
    intended, visible "the teacher changed" signal (ADR-0023, supersedes
    ADR-0020's frozen-snapshot scheme)."""
    return await render_persona_for_course(course_id, db)


async def build_system_prompt(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    kp_title: str,
    db: AsyncSession,
    *,
    turn_count: int,
    retrieval_chunks: list[str] | None = None,
) -> str:
    layer2 = await _build_layer2(course_id, db)
    layer3 = await _build_layer3(course_id, kp_id, kp_title, db)
    block = render_retrieval_block(retrieval_chunks or [])
    if block:
        layer3 = f"{layer3}\n\n{block}"
    return assemble_system_prompt(layer2, layer3, turn_count)
