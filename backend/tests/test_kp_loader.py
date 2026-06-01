"""Tests for the KP write-side: layout helpers, validators, generators.

The write side is split across three modules; this test file exercises
all three with shared fixtures:
- app.kp.exercise_layout: layout(), scaled_difficulty_mix(), constants
- app.kp.exercise_validators: schemas + structural validators
- app.kp.materializer: LLM generators + persist
"""
import json
from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest

from app.kp import exercise_layout as lay
from app.kp import exercise_validators as val
from app.kp import materializer as mat


# ---------- shared fixture payloads ----------


def _valid_material_payload() -> dict:
    return {
        "layer3_prompt": "用比较法引导学生理解加法的交换律与结合律。",
        "keyphrases": ["加法", "交换律", "结合律"],
        "knowledge_checklist": [
            {
                "concept": "交换律",
                "description": "加法中交换两个加数的位置，结果不变。",
                "must_anchor": True,
            },
            {
                "concept": "结合律",
                "description": "三个数相加，先加哪两个不影响结果。",
                "must_anchor": True,
            },
            {
                "concept": "加法单位元",
                "description": "0 是加法的单位元。",
                "must_anchor": False,
            },
        ],
    }


def _valid_exercise_payload(
    *,
    count: int = 5,
    mcq_qtypes: tuple[str, ...] = ("Definition", "Comparison", "Application"),
    short_qtype: str = "Inference",
) -> dict:
    """Build an exercise payload with `count` exercises following _layout."""
    layout = lay.layout(count)
    exercises: list[dict] = []
    mcq_idx = 0
    short_idx = 0
    for i, slot in enumerate(layout):
        if slot == "mcq":
            qtype = (
                mcq_qtypes[mcq_idx]
                if mcq_idx < len(mcq_qtypes)
                else mcq_qtypes[-1]
            )
            exercises.append(
                {
                    "type": "mcq",
                    "question_type": qtype,
                    "question": f"加法相关题 #{i+1}（涉及交换律、结合律）",
                    "options": [
                        {"label": "A", "text": "a+b=b+a"},
                        {"label": "B", "text": "a-b=b-a"},
                        {"label": "C", "text": "a*b=b*a"},
                        {"label": "D", "text": "a/b=b/a"},
                    ],
                    "correct_answer": "A",
                }
            )
            mcq_idx += 1
        else:
            exercises.append(
                {
                    "type": "short_answer",
                    "question_type": short_qtype if short_idx > 0 else "Application",
                    "question": f"请说说交换律的应用 #{i+1}",
                    "correct_answer": "交换律的实际场景。",
                    "grading_criteria": [
                        "点明交换律的定义",
                        "给出一个实际应用场景",
                    ],
                }
            )
            short_idx += 1
    return {"exercises": exercises}


def _make_fixture_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "加法的交换律：a+b=b+a。结合律：(a+b)+c=a+(b+c)。0 是单位元。")
    out = tmp_path / "fixture.pdf"
    doc.save(str(out))
    doc.close()
    return out


# ---------- KPMaterialPayload schema ----------


def test_material_schema_accepts_valid_payload():
    parsed = val.KPMaterialPayload.model_validate(_valid_material_payload())
    assert parsed.layer3_prompt
    assert len(parsed.keyphrases) >= 3


def test_material_schema_requires_at_least_one_must_anchor():
    bad = _valid_material_payload()
    for item in bad["knowledge_checklist"]:
        item["must_anchor"] = False  # zero must_anchor → invalid
    with pytest.raises(Exception):
        val.KPMaterialPayload.model_validate(bad)


def test_material_schema_rejects_too_few_checklist_items():
    bad = _valid_material_payload()
    bad["knowledge_checklist"] = bad["knowledge_checklist"][:2]
    with pytest.raises(Exception):
        val.KPMaterialPayload.model_validate(bad)


def test_material_schema_rejects_too_many_checklist_items():
    bad = _valid_material_payload()
    # New cap is 5 (was 7); 6 items must be rejected.
    base = bad["knowledge_checklist"][0]
    bad["knowledge_checklist"] = [dict(base, concept=f"c{i}") for i in range(6)]
    with pytest.raises(Exception):
        val.KPMaterialPayload.model_validate(bad)


def test_material_schema_rejects_too_few_keyphrases():
    bad = _valid_material_payload()
    bad["keyphrases"] = ["加法"]
    with pytest.raises(Exception):
        val.KPMaterialPayload.model_validate(bad)


# ---------- _layout (count [2, 7]) ----------


def test_layout_count_2():
    assert lay.layout(2) == ["mcq", "short_answer"]


def test_layout_count_3():
    assert lay.layout(3) == ["mcq", "mcq", "short_answer"]


def test_layout_count_5_default():
    assert lay.layout(5) == [
        "mcq", "mcq", "mcq", "short_answer", "short_answer"
    ]


def test_layout_count_7():
    layout = lay.layout(7)
    assert layout.count("mcq") + layout.count("short_answer") == 7
    # mcq before short_answer
    last_mcq = max(i for i, t in enumerate(layout) if t == "mcq")
    first_short = next(i for i, t in enumerate(layout) if t == "short_answer")
    assert last_mcq < first_short


def test_layout_rejects_out_of_range():
    with pytest.raises(ValueError):
        lay.layout(1)
    with pytest.raises(ValueError):
        lay.layout(8)


# ---------- _validate_layout ----------


def test_validate_layout_accepts_normal():
    payload = _valid_exercise_payload(count=5)
    parsed = val.ExerciseSetPayload.model_validate(payload)
    val.validate_layout(parsed.exercises, count=5)


def test_validate_layout_rejects_duplicate_mcq_qtypes():
    payload = _valid_exercise_payload(
        count=5, mcq_qtypes=("Definition", "Definition", "Application")
    )
    parsed = val.ExerciseSetPayload.model_validate(payload)
    with pytest.raises(ValueError):
        val.validate_layout(parsed.exercises, count=5)


def test_validate_layout_rejects_short_answer_with_options():
    payload = _valid_exercise_payload(count=5)
    payload["exercises"][3]["options"] = [
        {"label": "A", "text": "x"},
        {"label": "B", "text": "y"},
        {"label": "C", "text": "z"},
        {"label": "D", "text": "w"},
    ]
    parsed = val.ExerciseSetPayload.model_validate(payload)
    with pytest.raises(ValueError):
        val.validate_layout(parsed.exercises, count=5)


def test_validate_layout_rejects_mcq_with_bad_correct_answer():
    payload = _valid_exercise_payload(count=5)
    payload["exercises"][0]["correct_answer"] = "E"
    parsed = val.ExerciseSetPayload.model_validate(payload)
    with pytest.raises(ValueError):
        val.validate_layout(parsed.exercises, count=5)


# ---------- _validate_topic_whitelist ----------


def test_topic_whitelist_accepts_when_all_match():
    payload = _valid_exercise_payload(count=5)
    parsed = val.ExerciseSetPayload.model_validate(payload)
    val.validate_topic_whitelist(
        parsed.exercises,
        covered_concepts=["加法", "交换律", "结合律"],
    )


def test_topic_whitelist_rejects_off_topic_question():
    payload = _valid_exercise_payload(count=5)
    payload["exercises"][0]["question"] = "完全不相关的内容"
    parsed = val.ExerciseSetPayload.model_validate(payload)
    with pytest.raises(ValueError, match="未提及"):
        val.validate_topic_whitelist(
            parsed.exercises,
            covered_concepts=["加法"],
        )


def test_topic_whitelist_noop_when_concepts_empty():
    payload = _valid_exercise_payload(count=5)
    parsed = val.ExerciseSetPayload.model_validate(payload)
    val.validate_topic_whitelist(parsed.exercises, covered_concepts=[])


# ---------- _validate_difficulty_types ----------


def test_difficulty_easy_locks_per_slot():
    payload = _valid_exercise_payload(
        count=5,
        mcq_qtypes=("Definition", "Example", "Application"),
    )
    payload["exercises"][3]["question_type"] = "Application"
    payload["exercises"][4]["question_type"] = "Application"
    parsed = val.ExerciseSetPayload.model_validate(payload)
    val.validate_difficulty_types(
        parsed.exercises, difficulty="easy", count=5
    )


def test_difficulty_easy_rejects_wrong_type():
    payload = _valid_exercise_payload(
        count=5,
        mcq_qtypes=("Definition", "Example", "Comparison"),  # Comparison ≠ Application
    )
    payload["exercises"][3]["question_type"] = "Application"
    payload["exercises"][4]["question_type"] = "Application"
    parsed = val.ExerciseSetPayload.model_validate(payload)
    with pytest.raises(ValueError):
        val.validate_difficulty_types(
            parsed.exercises, difficulty="easy", count=5
        )


def test_difficulty_normal_is_noop():
    payload = _valid_exercise_payload(count=5)
    parsed = val.ExerciseSetPayload.model_validate(payload)
    val.validate_difficulty_types(
        parsed.exercises, difficulty="normal", count=5
    )


# ---------- generate_kp_material ----------


async def test_generate_kp_material_happy_path(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)

    async def stub(_api, _messages):
        return json.dumps(_valid_material_payload(), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    result = await mat.generate_kp_material(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
    )
    assert result.layer3_prompt
    assert len(result.keyphrases) >= 3
    assert any(item.must_anchor for item in result.knowledge_checklist)


async def test_generate_kp_material_retries_once(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    calls = {"n": 0}

    async def stub(_api, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json"
        return json.dumps(_valid_material_payload(), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    await mat.generate_kp_material(
        kp_title="加法", pdf_path=str(pdf), page_start=1, page_end=1
    )
    assert calls["n"] == 2


async def test_generate_kp_material_raises_after_retries_exhausted(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)

    async def stub(_api, _messages):
        return "bad json"

    monkeypatch.setattr(mat, "complete_json", stub)
    with pytest.raises(ValueError):
        await mat.generate_kp_material(
            kp_title="加法", pdf_path=str(pdf), page_start=1, page_end=1
        )


async def test_generate_kp_material_raises_on_empty_pdf_text(tmp_path, monkeypatch):
    """Empty PDF text triggers explicit error (image-only PDFs)."""
    doc = fitz.open()
    doc.new_page()  # blank page
    empty = tmp_path / "empty.pdf"
    doc.save(str(empty))
    doc.close()

    monkeypatch.setattr(
        mat, "complete_json", lambda *_: pytest.fail("should not call LLM")
    )
    with pytest.raises(ValueError, match="无法从 PDF 抽取"):
        await mat.generate_kp_material(
            kp_title="x", pdf_path=str(empty), page_start=1, page_end=1
        )


# ---------- generate_exercise_set ----------


async def test_generate_exercise_set_happy_path(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)

    async def stub(_api, _messages):
        return json.dumps(_valid_exercise_payload(count=5), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    result = await mat.generate_exercise_set(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
        keyphrases=["加法", "交换律", "结合律"],
        count=5,
    )
    assert len(result.exercises) == 5


async def test_generate_exercise_set_count_3(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)

    async def stub(_api, _messages):
        return json.dumps(_valid_exercise_payload(count=3), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    result = await mat.generate_exercise_set(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
        keyphrases=["加法", "交换律", "结合律"],
        count=3,
    )
    assert len(result.exercises) == 3


async def test_generate_exercise_set_invalid_difficulty_raises(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    monkeypatch.setattr(mat, "complete_json", lambda *_: pytest.fail("no LLM call expected"))
    with pytest.raises(ValueError, match="difficulty"):
        await mat.generate_exercise_set(
            kp_title="加法",
            pdf_path=str(pdf),
            page_start=1,
            page_end=1,
            keyphrases=["加法"],
            difficulty="extreme",
        )


async def test_generate_exercise_set_count_out_of_range_raises(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    monkeypatch.setattr(mat, "complete_json", lambda *_: pytest.fail("no LLM call expected"))
    with pytest.raises(ValueError, match="count"):
        await mat.generate_exercise_set(
            kp_title="加法",
            pdf_path=str(pdf),
            page_start=1,
            page_end=1,
            keyphrases=["加法"],
            count=1,
        )


async def test_generate_exercise_set_passes_covered_concepts_into_prompt(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    captured: list[dict] = []

    async def stub(_api, messages):
        captured.append(messages[1])  # user message
        return json.dumps(_valid_exercise_payload(count=5), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    await mat.generate_exercise_set(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
        keyphrases=["加法", "交换律", "结合律"],
        covered_concepts=["加法", "交换律", "结合律"],
        count=5,
    )
    user_content = captured[0]["content"]
    assert "考察范围（硬约束）" in user_content
    assert "「交换律」" in user_content


async def test_generate_exercise_set_retries_on_topic_off_whitelist(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    calls = {"n": 0}

    async def stub(_api, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            # First call: question 0 is off-whitelist
            payload = _valid_exercise_payload(count=5)
            payload["exercises"][0]["question"] = "完全无关的题"
            return json.dumps(payload, ensure_ascii=False)
        return json.dumps(_valid_exercise_payload(count=5), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    result = await mat.generate_exercise_set(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
        keyphrases=["加法", "交换律", "结合律"],
        covered_concepts=["加法", "交换律", "结合律"],
        count=5,
    )
    assert calls["n"] == 2
    assert len(result.exercises) == 5


async def test_generate_exercise_set_easy_difficulty_drives_prompt(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    captured: list[dict] = []

    async def stub(_api, messages):
        captured.append(messages[1])
        payload = _valid_exercise_payload(
            count=5, mcq_qtypes=("Definition", "Example", "Application")
        )
        payload["exercises"][3]["question_type"] = "Application"
        payload["exercises"][4]["question_type"] = "Application"
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    await mat.generate_exercise_set(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
        keyphrases=["加法", "交换律", "结合律"],
        difficulty="easy",
        count=5,
    )
    user_content = captured[0]["content"]
    assert "难度档：easy" in user_content


async def test_generate_exercise_set_normal_difficulty_omits_difficulty_block(tmp_path, monkeypatch):
    pdf = _make_fixture_pdf(tmp_path)
    captured: list[dict] = []

    async def stub(_api, messages):
        captured.append(messages[1])
        return json.dumps(_valid_exercise_payload(count=5), ensure_ascii=False)

    monkeypatch.setattr(mat, "complete_json", stub)
    await mat.generate_exercise_set(
        kp_title="加法",
        pdf_path=str(pdf),
        page_start=1,
        page_end=1,
        keyphrases=["加法", "交换律", "结合律"],
        difficulty="normal",
        count=5,
    )
    user_content = captured[0]["content"]
    assert "难度档" not in user_content
