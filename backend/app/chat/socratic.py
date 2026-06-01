"""Chat three-layer system prompt assembly.

Layer 1 (hard-coded, file-backed): pure Socratic teaching rules + meta
instructions telling the model to roleplay the Layer 2 scene.
Layer 2 (TeacherConfig persona): rendered by `app.courses.teacher_persona`.
Layer 3 (per-KP): teaching hint from KPMaterial + course position (where
this KP sits, what came before, what's next) from `app.courses.progress`.

Beyond turn 15 we append a directive nudging the LLM to ask the student
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
LAYER1_PROMPTS = {
    "zh": (_PROMPTS_DIR / "socratic_layer1.md").read_text(encoding="utf-8"),
    "en": (_PROMPTS_DIR / "socratic_layer1.en.md").read_text(encoding="utf-8"),
}


SOFT_TURN_CAP = 15

DIALOGUE_TEMPERATURE = 0.8


def count_turns(messages: list[Message]) -> int:
    """A turn = one user-sent message. Counts user messages in history."""
    return sum(1 for m in messages if m.role == MessageRole.user)


_L3 = {
    "zh": {
        "no_hint": "（暂无教材切入点，基于学生回答自行推进；不引入文本外内容）",
        "none": "（无）",
        "first": "（这是第一个知识点）",
        "last": "（这是最后一个知识点）",
        "sep": "、",
        "tmpl": (
            "当前学习上下文：\n"
            "- 你正在教第 {pos} 个知识点：「{kp_title}」\n"
            "- 学生之前学过：{prev}\n"
            "- 接下来还要学：{nxt}\n"
            "- 该 KP 的核心关键词：{keyphrases}\n"
            "\n"
            "KP 教学切入点：{hint}"
        ),
    },
    "en": {
        "no_hint": "(no material entry point; advance based on the student's answers; don't introduce content outside the text)",
        "none": "(none)",
        "first": "(this is the first knowledge point)",
        "last": "(this is the last knowledge point)",
        "sep": ", ",
        "tmpl": (
            "Current learning context:\n"
            '- You are teaching knowledge point #{pos}: "{kp_title}"\n'
            "- The student previously studied: {prev}\n"
            "- Coming up next: {nxt}\n"
            "- This KP's core keyphrases: {keyphrases}\n"
            "\n"
            "KP teaching entry point: {hint}"
        ),
    },
}


async def _build_layer3(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    kp_title: str,
    db: AsyncSession,
    lang: str = "zh",
) -> str:
    from app.kp.loader import get_kp_material

    t = _L3[lang]
    pos, prev, nxt = await get_kp_position(course_id, kp_id, db)
    material = await get_kp_material(db, kp_id)
    teaching_hint = (
        material.layer3_prompt if material is not None else t["no_hint"]
    )
    keyphrases = (
        t["sep"].join(material.keyphrases)
        if material is not None and material.keyphrases
        else t["none"]
    )

    prev_str = t["sep"].join(prev) if prev else t["first"]
    next_str = t["sep"].join(nxt) if nxt else t["last"]

    checklist_block = render_checklist_block(
        material.knowledge_checklist if material is not None else [], lang
    )

    base = t["tmpl"].format(
        pos=pos,
        kp_title=kp_title,
        prev=prev_str,
        nxt=next_str,
        keyphrases=keyphrases,
        hint=teaching_hint,
    )
    if checklist_block:
        return f"{base}\n\n{checklist_block}"
    return base


_CHECKLIST_HEADER = {
    "zh": "该 KP 必须覆盖的知识清单（请确保对话中逐一覆盖；标记 ★ 的概念**必须**经过锚定阶段）：",
    "en": "The knowledge checklist this KP must cover (make sure each is covered "
    "in the dialogue; concepts marked ★ **must** go through the anchor phase):",
}


def render_checklist_block(checklist: list[dict] | None, lang: str = "zh") -> str:
    """Pure: render a knowledge_checklist (list of {concept, description,
    must_anchor}) into a Layer 3 addendum. Returns "" when empty.

    must_anchor items get a leading "★" so the dialogue LLM treats it as
    typography, not as part of the concept name."""
    if not checklist:
        return ""
    lines = [_CHECKLIST_HEADER[lang]]
    for item in checklist:
        concept = item.get("concept", "")
        desc = item.get("description", "")
        marker = "★ " if item.get("must_anchor") else "  "
        lines.append(f"{marker}「{concept}」：{desc}")
    return "\n".join(lines)


_SOFT_CAP = {
    "zh": (
        "对话已进行 {n} 轮，达到 {cap} 轮软上限。"
        "本轮**必须**主动询问学生：「要不要进作业？」并提供 3 个选项："
        "1. 继续学习  2. 进作业页做练习  3. 休息一下。"
        "如果学生选择继续学习，可以继续推进，不要强行结束。"
    ),
    "en": (
        "The dialogue has run {n} turns, reaching the {cap}-turn soft cap. "
        "This turn you **must** proactively ask the student: \"Want to move to "
        "the exercises?\" and offer 3 options: "
        "1. Keep learning  2. Go to the exercise page  3. Take a break. "
        "If the student chooses to keep learning, continue — don't force an end."
    ),
}


def _soft_cap_directive(turn_count: int, lang: str = "zh") -> str:
    return _SOFT_CAP[lang].format(n=turn_count, cap=SOFT_TURN_CAP)


_RETRIEVAL_HEADER = {
    "zh": "该知识点的教材原文（请基于以下内容进行教学，不引入文本外的内容）：",
    "en": "The source text for this KP (teach based on the content below; do not "
    "introduce content outside it):",
}
_EXCERPT_LABEL = {"zh": "片段", "en": "Excerpt"}


def render_retrieval_block(chunks: list[str], lang: str = "zh") -> str:
    """Pure: format retrieved PDF excerpts as a Layer 3 addendum."""
    if not chunks:
        return ""
    lines = [_RETRIEVAL_HEADER[lang]]
    for i, c in enumerate(chunks, 1):
        lines.append(f"[{_EXCERPT_LABEL[lang]} {i}] {c}")
    return "\n".join(lines)


def assemble_system_prompt(
    layer2: str, layer3: str, turn_count: int, lang: str = "zh"
) -> str:
    """Pure assembly of the three layers + optional soft-cap directive."""
    parts = [LAYER1_PROMPTS[lang], layer2, layer3]
    if turn_count >= SOFT_TURN_CAP:
        parts.append(_soft_cap_directive(turn_count, lang))
    return "\n\n".join(parts)


async def _build_layer2(
    course_id: uuid.UUID, db: AsyncSession, lang: str = "zh"
) -> str:
    """Always render the live TeacherConfig persona. Persona edits take
    effect on the next turn — including mid-conversation — which is the
    intended, visible "the teacher changed" signal (ADR-0023, supersedes
    ADR-0020's frozen-snapshot scheme)."""
    return await render_persona_for_course(course_id, db, lang)


async def build_system_prompt(
    course_id: uuid.UUID,
    kp_id: uuid.UUID,
    kp_title: str,
    db: AsyncSession,
    *,
    turn_count: int,
    retrieval_chunks: list[str] | None = None,
    lang: str = "zh",
) -> str:
    layer2 = await _build_layer2(course_id, db, lang)
    layer3 = await _build_layer3(course_id, kp_id, kp_title, db, lang)
    block = render_retrieval_block(retrieval_chunks or [], lang)
    if block:
        layer3 = f"{layer3}\n\n{block}"
    return assemble_system_prompt(layer2, layer3, turn_count, lang)
