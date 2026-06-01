import uuid

from app.chat import socratic
from app.courses import teacher_persona
from app.models import Message, MessageRole


SOFT_CAP_MARKER = "本轮**必须**主动询问"


def _msg(role: MessageRole, content: str = "x") -> Message:
    return Message(
        id=uuid.uuid4(),
        kp_id=uuid.uuid4(),
        role=role,
        content=content,
    )


def test_count_turns_only_counts_user_messages():
    history = [
        _msg(MessageRole.user),
        _msg(MessageRole.assistant),
        _msg(MessageRole.user),
        _msg(MessageRole.user),
        _msg(MessageRole.assistant),
    ]
    assert socratic.count_turns(history) == 3


def test_count_turns_on_empty_history():
    assert socratic.count_turns([]) == 0


def test_layer1_prompt_loads_rules_only():
    text = socratic.LAYER1_PROMPTS["zh"]
    assert "苏格拉底" in text
    # Layer 1 is now persona-agnostic — no hard-coded few-shots there.
    assert "三月七" not in text
    # The four-stage teaching cycle is the heart of Layer 1.
    assert "诊断" in text
    assert "引导" in text
    assert "锚定" in text
    assert "迁移" in text


def test_default_scene_loads_and_describes_persona():
    assert "费曼" in teacher_persona.default_scene()


def test_render_persona_with_all_three_parts():
    text = teacher_persona.render_persona(
        scene="你是一名严肃的物理学教授，注重逻辑严密",
        learner_context="大二学生，目标是期末考过 80 分",
        few_shots="## 示例 1：开场\n\n老师：你对这个知识点已经了解什么？",
    )
    assert "严肃的物理学教授" in text
    assert "大二学生" in text
    assert "示例 1：开场" in text
    assert "# 你的角色" in text
    assert "# Few-shot 示例" in text
    assert "# 学习者上下文" in text


def test_render_persona_handles_missing_few_shots_via_fallback():
    text = teacher_persona.render_persona(
        scene="某个具体场景",
        learner_context="某个背景",
        few_shots=None,
    )
    assert teacher_persona.PERSONA_FALLBACK_FEW_SHOTS in text


def test_render_persona_handles_blank_few_shots_via_fallback():
    text = teacher_persona.render_persona(
        scene="某个具体场景",
        learner_context="某个背景",
        few_shots="   \n  ",
    )
    assert teacher_persona.PERSONA_FALLBACK_FEW_SHOTS in text


def test_render_persona_falls_back_when_scene_and_context_blank():
    text = teacher_persona.render_persona(
        scene="   ", learner_context="\t", few_shots=None
    )
    assert teacher_persona.PERSONA_FALLBACK_SCENE in text
    assert teacher_persona.PERSONA_FALLBACK_CONTEXT in text


def test_soft_cap_directive_includes_threshold_and_action():
    out = socratic._soft_cap_directive(turn_count=22)
    assert "22" in out
    assert str(socratic.SOFT_TURN_CAP) in out
    assert "进作业" in out


def test_assemble_system_prompt_contains_three_layers():
    layer2 = "<<MARKER LAYER2 CONTENT>>"
    layer3 = "<<MARKER LAYER3 CONTENT>>"
    prompt = socratic.assemble_system_prompt(layer2, layer3, turn_count=3)
    assert "苏格拉底" in prompt
    assert "<<MARKER LAYER2 CONTENT>>" in prompt
    assert "<<MARKER LAYER3 CONTENT>>" in prompt
    assert SOFT_CAP_MARKER not in prompt


def test_assemble_system_prompt_appends_soft_cap_at_threshold():
    prompt = socratic.assemble_system_prompt(
        "layer2", "layer3", turn_count=socratic.SOFT_TURN_CAP
    )
    assert SOFT_CAP_MARKER in prompt


def test_assemble_system_prompt_appends_soft_cap_above_threshold():
    prompt = socratic.assemble_system_prompt("layer2", "layer3", turn_count=22)
    assert SOFT_CAP_MARKER in prompt


def test_assemble_system_prompt_no_soft_cap_below_threshold():
    prompt = socratic.assemble_system_prompt(
        "layer2", "layer3", turn_count=socratic.SOFT_TURN_CAP - 1
    )
    assert SOFT_CAP_MARKER not in prompt


# ---------- knowledge_checklist rendering (Task 2) ----------


def test_render_checklist_block_empty_returns_empty_string():
    """Legacy KP content (pre-migration 0017) has empty checklist; renderer
    must degrade silently so old courses keep working."""
    assert socratic.render_checklist_block([]) == ""
    assert socratic.render_checklist_block(None) == ""


def test_render_checklist_block_with_items():
    items = [
        {
            "concept": "导数定义",
            "description": "极限形式",
            "must_anchor": True,
        },
        {
            "concept": "导数几何意义",
            "description": "切线斜率",
            "must_anchor": True,
        },
        {
            "concept": "高阶导数",
            "description": "导数的导数",
            "must_anchor": False,
        },
    ]
    block = socratic.render_checklist_block(items)
    # Header signals the LLM these are to be covered.
    assert "知识清单" in block
    assert "锚定" in block
    # must_anchor items are marked with star at line start; concept names
    # are wrapped in 「」 so the LLM treats them as opaque tokens.
    assert "★ 「导数定义」" in block
    assert "★ 「导数几何意义」" in block
    # Non-anchored items appear without star prefix on their line.
    assert "「高阶导数」" in block
    assert "★ 「高阶导数」" not in block
    # Descriptions are rendered.
    assert "极限形式" in block
    assert "切线斜率" in block
