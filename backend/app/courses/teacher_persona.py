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
DEFAULT_SCENE = (_PROMPTS_DIR / "default_scene.md").read_text(encoding="utf-8")


PERSONA_FALLBACK_SCENE = "你是一位耐心、循循善诱的虚拟家教。"
PERSONA_FALLBACK_CONTEXT = "学习者背景与目标暂未提供，请在对话中适时询问。"
PERSONA_FALLBACK_FEW_SHOTS = (
    "（暂无人设对话示例，请严格依据上方场景描述自然演绎角色的语气、用词与神态。）"
)


def render_persona(
    scene: str,
    learner_context: str,
    few_shots: str | None,
) -> str:
    """Pure: format scene + learner_context + cached few-shots into the
    persona block consumed by the chat LLM (occupies "Layer 2" of the
    three-layer system prompt)."""
    scene_block = scene.strip() or PERSONA_FALLBACK_SCENE
    context_block = learner_context.strip() or PERSONA_FALLBACK_CONTEXT
    few_shots_block = (few_shots or "").strip() or PERSONA_FALLBACK_FEW_SHOTS
    return (
        "# 你的角色\n\n"
        f"{scene_block}\n\n"
        "# Few-shot 示例\n\n"
        f"{few_shots_block}\n\n"
        "# 学习者上下文\n\n"
        f"{context_block}"
    )


async def render_persona_for_course(
    course_id: uuid.UUID, db: AsyncSession
) -> str:
    """Render the persona block from the live TeacherConfig (or
    fallbacks if absent)."""
    config = await db.get(TeacherConfig, course_id)
    if config is None:
        return render_persona("", "", None)
    return render_persona(
        config.scene,
        config.learner_context,
        config.generated_few_shots,
    )
