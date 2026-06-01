"""Persona-matched few-shot generator.

Given a teacher scene description (Layer 2 `scene`), call the LLM to produce
a markdown block of 6 example dialogues that imitate the scene's voice and
demeanor. The result is cached on `TeacherConfig.generated_few_shots` and
re-injected into Layer 2 at chat time, so a custom persona ends up just as
vivid as a hard-coded one.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from app.lang import lang_of
from app.llm import complete_json

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
FEW_SHOT_SYSTEM_PROMPTS = {
    "zh": (_PROMPT_DIR / "persona_few_shot_generation.md").read_text(encoding="utf-8"),
    "en": (_PROMPT_DIR / "persona_few_shot_generation.en.md").read_text(encoding="utf-8"),
}
_SCENE_LABEL = {"zh": "教师场景", "en": "Teacher scene"}


def compute_scene_signature(scene: str) -> str:
    """Stable signature for a scene string; used to detect whether a cached
    few-shot block still corresponds to the current scene."""
    return hashlib.sha256(scene.strip().encode("utf-8")).hexdigest()


async def generate_few_shots(
    scene: str, *, api_settings: dict | None = None
) -> str:
    """Call the LLM to produce a markdown few-shot block for the given scene.

    Returns "" on any failure (so callers can persist scene/context regardless
    and surface a "regenerate" affordance to the user)."""
    scene_stripped = scene.strip()
    if not scene_stripped:
        return ""

    lang = lang_of(api_settings)
    messages = [
        {"role": "system", "content": FEW_SHOT_SYSTEM_PROMPTS[lang]},
        {"role": "user", "content": f"{_SCENE_LABEL[lang]}：\n\n{scene_stripped}"},
    ]
    try:
        raw = await complete_json(api_settings, messages)
        data = json.loads(raw)
        few_shots = data.get("few_shots_markdown", "")
        if not isinstance(few_shots, str):
            raise ValueError(
                f"few_shots_markdown is not a string: {type(few_shots).__name__}"
            )
        return few_shots.strip()
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Few-shot generation failed: %s", exc)
        return ""
    except Exception as exc:  # pragma: no cover - unexpected upstream errors
        logger.exception("Unexpected few-shot generation error: %s", exc)
        return ""
