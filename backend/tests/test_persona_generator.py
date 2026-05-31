import json

import pytest

from app.chat import persona_generator


def test_compute_scene_signature_stable_for_same_input():
    a = persona_generator.compute_scene_signature("hello\n")
    b = persona_generator.compute_scene_signature("  hello   ")
    assert a == b


def test_compute_scene_signature_differs_for_different_input():
    a = persona_generator.compute_scene_signature("scene one")
    b = persona_generator.compute_scene_signature("scene two")
    assert a != b


@pytest.mark.asyncio
async def test_generate_few_shots_returns_markdown_from_llm_json(monkeypatch):
    async def fake_complete(_api, messages):
        assert messages[0]["role"] == "system"
        assert "教师场景" in messages[1]["content"]
        return json.dumps({"few_shots_markdown": "## 示例 1\n\n老师：…"})

    monkeypatch.setattr(persona_generator, "complete_json", fake_complete)
    out = await persona_generator.generate_few_shots("一段场景叙述")
    assert "示例 1" in out


@pytest.mark.asyncio
async def test_generate_few_shots_returns_empty_on_blank_scene():
    out = await persona_generator.generate_few_shots("   ")
    assert out == ""


@pytest.mark.asyncio
async def test_generate_few_shots_swallows_invalid_json(monkeypatch):
    async def fake_complete(_api, _):
        return "not json"

    monkeypatch.setattr(persona_generator, "complete_json", fake_complete)
    out = await persona_generator.generate_few_shots("scene")
    assert out == ""


@pytest.mark.asyncio
async def test_generate_few_shots_swallows_wrong_field_type(monkeypatch):
    async def fake_complete(_api, _):
        return json.dumps({"few_shots_markdown": ["not", "a", "string"]})

    monkeypatch.setattr(persona_generator, "complete_json", fake_complete)
    out = await persona_generator.generate_few_shots("scene")
    assert out == ""
