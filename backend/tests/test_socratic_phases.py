"""Tests for Layer 1 four-stage teaching cycle.

These assertions don't run the LLM — they verify that the prompt files we
ship contain the structural elements the orchestration code relies on.
A regression here means the prompt was edited in a way that loses the
diagnose→guide→anchor→transfer scaffold (the contract Layer 3 and the
assessor will read against).
"""

from app.chat import socratic


def test_layer1_contains_four_stages():
    text = socratic.LAYER1_PROMPTS["zh"]
    assert "阶段 1：诊断" in text
    assert "阶段 2：引导" in text
    assert "阶段 3：锚定" in text
    assert "阶段 4：迁移" in text


def test_layer1_anchoring_stage_specifies_definition_formula_example():
    """The anchoring stage is the only place the LLM is permitted to
    expand beyond 1-3 sentences. The prompt must explicitly call out the
    three components or it'll regress to "endless questioning"."""
    text = socratic.LAYER1_PROMPTS["zh"]
    # Anchoring section must mention the three required components.
    assert "核心定义" in text
    assert "公式" in text
    assert "例子" in text
    # And must permit a longer reply.
    assert "4-8 句" in text


def test_layer1_specifies_anchoring_triggers():
    """If the LLM doesn't know WHEN to anchor, it'll never anchor.
    The triggers (接近正确 / 连续两次答错 / 5 轮以上) must be in the prompt."""
    text = socratic.LAYER1_PROMPTS["zh"]
    assert "接近正确" in text
    assert "连续两次答错" in text or "连续两次" in text
    assert "5 轮" in text


def test_layer1_self_check_mechanism_present():
    """The 'every 5 rounds self-check' is the safety net that prevents
    the model from drifting back into infinite questioning."""
    text = socratic.LAYER1_PROMPTS["zh"]
    assert "自查" in text
    assert "5 轮" in text


def test_layer1_references_knowledge_checklist():
    """Layer 3 will inject a knowledge_checklist; Layer 1 must reference
    it so the model knows starred concepts must be anchored."""
    text = socratic.LAYER1_PROMPTS["zh"]
    assert "knowledge_checklist" in text or "知识清单" in text
    assert "★" in text  # the star marker for must-anchor concepts


def test_layer1_preserves_red_lines():
    """The cross-stage red lines (textbook grounding, LaTeX, resistance
    handling) must survive the four-stage refactor."""
    text = socratic.LAYER1_PROMPTS["zh"]
    # Resistance handling: pivot approach, not a rigid 3-option menu.
    assert "换个方向" in text or "抗拒" in text
    # LaTeX requirement.
    assert "$" in text
    assert "LaTeX" in text
    # Persona styling via *italic* narration.
    assert "*斜体*" in text


def test_sakiko_persona_includes_anchoring_example():
    """The Sakiko persona ships its own few-shots inline. The anchoring
    example (示例 6) is the highest-stakes one—if persona few-shots stay
    purely interrogative, the model imitates that and never anchors."""
    from pathlib import Path

    sakiko_path = (
        Path(socratic.__file__).parent.parent / "prompts" / "socratic_layer1_Sakiko.md"
    )
    text = sakiko_path.read_text(encoding="utf-8")
    assert "示例 6" in text
    assert "锚定" in text
    # The anchoring few-shot must contain a definition + LaTeX formula.
    assert "$f'(x)" in text or "$a^2" in text
    # And must transition with one of the canonical anchoring phrases.
    assert (
        "也就是说" in text
        or "我直接告诉你" in text
        or "准确的说法" in text
    )


def test_persona_few_shot_generation_prompt_requires_anchoring_case():
    """The LLM that generates few-shots for new personas must produce an
    anchoring example, otherwise the dynamic persona path silently
    regresses to interrogation-only."""
    from pathlib import Path

    prompt_path = (
        Path(socratic.__file__).parent.parent
        / "prompts"
        / "persona_few_shot_generation.md"
    )
    text = prompt_path.read_text(encoding="utf-8")
    # Generator must demand 7 examples now (was 6).
    assert "7 段" in text or "7 种" in text
    # Anchoring case must be explicitly listed.
    assert "锚定" in text
    # Anchoring case must require definition + formula + example.
    assert "定义" in text
    assert "公式" in text
    assert "例子" in text or "验证题" in text


def test_layer1_stage_specific_reply_lengths():
    """Different stages get different reply-length budgets. The table
    must enumerate them so the LLM doesn't squeeze anchoring into short replies."""
    text = socratic.LAYER1_PROMPTS["zh"]
    # Anchoring must have a significantly larger budget than other stages.
    assert "4-8 句" in text  # 锚定（成人版扩展）
    # Guidance and transfer have distinct budgets.
    assert "2-4 句" in text  # 引导
    assert "3-5 句" in text  # 迁移
