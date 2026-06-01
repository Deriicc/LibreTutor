"""Teacher persona rendering.

Renders a `TeacherConfig` (scene + learner_context + cached few-shots)
into the text block that drives the dialogue LLM's persona behavior.
Rendered live every chat turn — no snapshotting (ADR-0023, supersedes
ADR-0020); persona edits take effect on the next turn.

Pure helpers + a DB-aware orchestrator. Consumers:
- `app.chat.socratic._build_layer2` — assembles current Layer 2 for chat
- `app.courses.router` — test-chat preview
"""

from __future__ import annotations

import uuid

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TeacherConfig


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
DEFAULT_SCENES = {
    "zh": (_PROMPTS_DIR / "default_scene.md").read_text(encoding="utf-8"),
    "en": (_PROMPTS_DIR / "default_scene.en.md").read_text(encoding="utf-8"),
}


def default_scene(lang: str = "zh") -> str:
    """The seeded default teacher scene (shown in the teacher-config UI when
    a course has no scene yet)."""
    return DEFAULT_SCENES.get(lang, DEFAULT_SCENES["zh"])


_PERSONA = {
    "zh": {
        "scene": "你是一位耐心、循循善诱的虚拟家教。",
        "context": "学习者背景与目标暂未提供，请在对话中适时询问。",
        "few_shots": "（暂无人设对话示例，请严格依据上方场景描述自然演绎角色的语气、用词与神态。）",
        "h_role": "你的角色",
        "h_few": "Few-shot 示例",
        "h_ctx": "学习者上下文",
    },
    "en": {
        "scene": "You are a patient, guiding virtual tutor.",
        "context": "The learner's background and goals aren't provided yet; ask at suitable moments in the dialogue.",
        "few_shots": "(No persona dialogue examples yet; follow the scene above to naturally render the role's tone, word choice, and demeanor.)",
        "h_role": "Your role",
        "h_few": "Few-shot examples",
        "h_ctx": "Learner context",
    },
}


# Public zh-default aliases (readable constants; also used in tests).
PERSONA_FALLBACK_SCENE = _PERSONA["zh"]["scene"]
PERSONA_FALLBACK_CONTEXT = _PERSONA["zh"]["context"]
PERSONA_FALLBACK_FEW_SHOTS = _PERSONA["zh"]["few_shots"]


def render_persona(
    scene: str,
    learner_context: str,
    few_shots: str | None,
    lang: str = "zh",
) -> str:
    """Pure: format scene + learner_context + cached few-shots into the
    persona block consumed by the chat LLM (occupies "Layer 2" of the
    three-layer system prompt)."""
    p = _PERSONA[lang]
    scene_block = scene.strip() or p["scene"]
    context_block = learner_context.strip() or p["context"]
    few_shots_block = (few_shots or "").strip() or p["few_shots"]
    return (
        f"# {p['h_role']}\n\n"
        f"{scene_block}\n\n"
        f"# {p['h_few']}\n\n"
        f"{few_shots_block}\n\n"
        f"# {p['h_ctx']}\n\n"
        f"{context_block}"
    )


async def render_persona_for_course(
    course_id: uuid.UUID, db: AsyncSession, lang: str = "zh"
) -> str:
    """Render the persona block from the live TeacherConfig (or
    fallbacks if absent)."""
    config = await db.get(TeacherConfig, course_id)
    if config is None:
        return render_persona("", "", None, lang)
    return render_persona(
        config.scene,
        config.learner_context,
        config.generated_few_shots,
        lang,
    )
