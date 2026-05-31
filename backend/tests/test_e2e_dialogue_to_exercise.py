"""End-to-end test for the dialogue → assessment → exercise pipeline.

Mocks the LLM at two call sites:
- Assessor (`app.kp.assessor.complete_json`)
- Exercise set generator (`app.kp.materializer.complete_json`)

Each profile drives the assessor toward different coverage_ratio values,
which in turn drive different (difficulty, count) suggestions, which the
exercise generator must honor.

Material is seeded directly via KPMaterial so the assessor has a checklist
to evaluate against (in production this comes from the prewarm path).
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.kp import assessor as assessor_module
from app.kp import materializer as materializer_module
from app.kp.assessor import run_assessment
from app.kp.materializer import generate_exercise_set
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    KnowledgePoint,
    KPAssessment,
    KPMaterial,
    Message,
    MessageRole,
    Section,
)


CHECKLIST = [
    {
        "concept": "导数定义",
        "description": "极限形式 f'(x)=lim h→0 (f(x+h)-f(x))/h",
        "must_anchor": True,
    },
    {
        "concept": "切线斜率",
        "description": "导数的几何意义",
        "must_anchor": True,
    },
    {
        "concept": "可导与连续",
        "description": "可导一定连续，反之不一定",
        "must_anchor": False,
    },
]

KEYPHRASES = ["导数", "极限", "斜率"]


async def _setup_kp_with_chat(
    history: list[tuple[MessageRole, str]],
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Build a course/chapter/section/KP with a material row + chat history.
    Returns (course_id, kp_id, source_path)."""
    async with SessionLocal() as db:
        course = Course(
            name="e2e",
            source_pdf_path="",
            generation_status=GenerationStatus.done,
        )
        db.add(course)
        await db.flush()
        chapter = Chapter(course_id=course.id, title="ch", order_index=0)
        db.add(chapter)
        await db.flush()
        section = Section(chapter_id=chapter.id, title="sec", order_index=0)
        db.add(section)
        await db.flush()
        kp = KnowledgePoint(
            section_id=section.id,
            title="导数",
            order_index=0,
            boundary={"page_start": 1, "page_end": 2},
        )
        db.add(kp)
        await db.flush()

        db.add(
            KPMaterial(
                kp_id=kp.id,
                layer3_prompt="切入点：从平均速度引入瞬时变化率",
                keyphrases=KEYPHRASES,
                knowledge_checklist=CHECKLIST,
            )
        )
        for role, content in history:
            db.add(Message(kp_id=kp.id, role=role, content=content))
        await db.commit()
        return course.id, kp.id, course.source_pdf_path


def _make_pdf_at(tmp_path):
    import fitz  # type: ignore[import-untyped]

    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text(
            (50, 72), f"page {i+1}: 导数是函数的瞬时变化率。切线斜率即导数。"
        )
    out = tmp_path / "e2e.pdf"
    doc.save(str(out))
    doc.close()
    return str(out)


def _assessment_payload_for(
    *,
    covered: list[str],
    partial: list[str],
    untouched: list[str],
    difficulty: str,
    count: int,
) -> str:
    ratio = round((len(covered) + 0.5 * len(partial)) / 3, 2)
    return json.dumps(
        {
            "covered": [
                {"concept": c, "evidence": f"对话中讨论了 {c}"} for c in covered
            ],
            "partial": [
                {"concept": p, "evidence": f"提到 {p} 但未展开"} for p in partial
            ],
            "untouched": [
                {"concept": u, "reason": "对话中未涉及"} for u in untouched
            ],
            "coverage_ratio": ratio,
            "mastery_summary": "auto-generated for e2e test",
            "suggested_difficulty": difficulty,
            "suggested_count": count,
        }
    )


def _exercise_payload(
    *,
    count: int,
    difficulty: str,
    concept_per_question: list[str],
) -> dict:
    """Build an exercise set payload for `count` exercises whose questions
    each include the matching concept text. Layout follows _layout."""
    from app.kp import exercise_layout

    layout = exercise_layout.layout(count)
    mix = exercise_layout.scaled_difficulty_mix(difficulty, count)
    fallback_mcq_types = ["Definition", "Comparison", "Application", "Inference"]
    fallback_short_types = ["Application", "Comparison", "Inference"]
    exercises: list[dict] = []
    mcq_idx = 0
    short_idx = 0
    for i, slot_type in enumerate(layout):
        concept = concept_per_question[i]
        if slot_type == "mcq":
            qtype = (
                mix["mcq"][mcq_idx]
                if mix["mcq"]
                else fallback_mcq_types[mcq_idx % len(fallback_mcq_types)]
            )
            exercises.append(
                {
                    "type": "mcq",
                    "question_type": qtype,
                    "question": f"关于「{concept}」的题目 #{i+1}",
                    "options": [
                        {"label": "A", "text": "选项A"},
                        {"label": "B", "text": "选项B"},
                        {"label": "C", "text": "选项C"},
                        {"label": "D", "text": "选项D"},
                    ],
                    "correct_answer": "A",
                }
            )
            mcq_idx += 1
        else:
            qtype = (
                mix["short_answer"][short_idx]
                if mix["short_answer"]
                else fallback_short_types[
                    short_idx % len(fallback_short_types)
                ]
            )
            exercises.append(
                {
                    "type": "short_answer",
                    "question_type": qtype,
                    "question": f"请说说「{concept}」的应用 #{i+1}",
                    "correct_answer": "...",
                    "grading_criteria": [
                        f"点明「{concept}」的核心含义",
                        "结合一个具体场景说明",
                    ],
                }
            )
            short_idx += 1
    return {"exercises": exercises}


async def test_profile_engaged_student_drives_normal_difficulty_5_questions(
    tmp_path, monkeypatch
):
    pdf_path = _make_pdf_at(tmp_path)
    course_id, kp_id, _ = await _setup_kp_with_chat(
        history=[
            (MessageRole.assistant, "你对导数知道什么？"),
            (MessageRole.user, "感觉是变化率的意思"),
            (MessageRole.assistant, "切线斜率呢？"),
            (MessageRole.user, "切线的斜率就是导数对吧"),
            (MessageRole.assistant, "可导与连续什么关系？"),
            (MessageRole.user, "可导一定连续，反过来不一定"),
        ],
    )
    async with SessionLocal() as db:
        from sqlalchemy import update

        await db.execute(
            update(Course).where(Course.id == course_id).values(source_pdf_path=pdf_path)
        )
        await db.commit()

    async def assess_stub(_api, _messages):
        return _assessment_payload_for(
            covered=["导数定义", "切线斜率", "可导与连续"],
            partial=[],
            untouched=[],
            difficulty="normal",
            count=5,
        )

    monkeypatch.setattr(assessor_module, "complete_json", assess_stub)

    async with SessionLocal() as db:
        a = await run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert float(a.coverage_ratio) == 1.0
        assert a.suggested_difficulty == "normal"
        assert a.suggested_count == 5

    async def gen_stub(_api, _messages):
        return json.dumps(
            _exercise_payload(
                count=5,
                difficulty="normal",
                concept_per_question=[
                    "导数定义",
                    "切线斜率",
                    "可导与连续",
                    "导数定义",
                    "切线斜率",
                ],
            ),
            ensure_ascii=False,
        )

    monkeypatch.setattr(materializer_module, "complete_json", gen_stub)
    result = await generate_exercise_set(
        kp_title="导数",
        pdf_path=pdf_path,
        page_start=1,
        page_end=2,
        keyphrases=KEYPHRASES,
        covered_concepts=["导数定义", "切线斜率", "可导与连续"],
        difficulty="normal",
        count=5,
    )
    assert len(result.exercises) == 5
    for e in result.exercises:
        assert any(
            c in e.question for c in ["导数定义", "切线斜率", "可导与连续"]
        )


async def test_profile_disengaged_student_drives_easy_difficulty_2_questions(
    tmp_path, monkeypatch
):
    pdf_path = _make_pdf_at(tmp_path)
    course_id, kp_id, _ = await _setup_kp_with_chat(
        history=[
            (MessageRole.assistant, "你对导数知道什么？"),
            (MessageRole.user, "不知道"),
            (MessageRole.assistant, "听过切线吗？"),
            (MessageRole.user, "没"),
        ],
    )
    async with SessionLocal() as db:
        from sqlalchemy import update

        await db.execute(
            update(Course).where(Course.id == course_id).values(source_pdf_path=pdf_path)
        )
        await db.commit()

    async def assess_stub(_api, _messages):
        return _assessment_payload_for(
            covered=[],
            partial=["切线斜率"],
            untouched=["导数定义", "可导与连续"],
            difficulty="easy",
            count=2,
        )

    monkeypatch.setattr(assessor_module, "complete_json", assess_stub)

    async with SessionLocal() as db:
        a = await run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert a.suggested_difficulty == "easy"
        assert a.suggested_count == 2
        assert float(a.coverage_ratio) < 0.6

    async def gen_stub(_api, _messages):
        return json.dumps(
            _exercise_payload(
                count=2,
                difficulty="easy",
                concept_per_question=["切线斜率", "切线斜率"],
            ),
            ensure_ascii=False,
        )

    monkeypatch.setattr(materializer_module, "complete_json", gen_stub)
    result = await generate_exercise_set(
        kp_title="导数",
        pdf_path=pdf_path,
        page_start=1,
        page_end=2,
        keyphrases=KEYPHRASES,
        covered_concepts=["切线斜率"],
        difficulty="easy",
        count=2,
    )
    assert len(result.exercises) == 2
    assert result.exercises[0].type == "mcq"
    assert result.exercises[1].type == "short_answer"
    assert result.exercises[0].question_type == "Definition"
    for e in result.exercises:
        assert "切线斜率" in e.question


async def test_profile_advanced_student_drives_hard_difficulty(
    tmp_path, monkeypatch
):
    pdf_path = _make_pdf_at(tmp_path)
    course_id, kp_id, _ = await _setup_kp_with_chat(
        history=[
            (MessageRole.assistant, "你对导数知道什么？"),
            (MessageRole.user, "导数 = lim_{h→0} (f(x+h)-f(x))/h，是切线斜率"),
            (MessageRole.assistant, "可导与连续呢？"),
            (
                MessageRole.user,
                "可导一定连续，但 |x| 在 0 处连续不可导，因为左右导数不等",
            ),
            (MessageRole.assistant, "什么时候导数不存在？"),
            (
                MessageRole.user,
                "尖点、垂直切线、跳跃间断点；本质是 (f(x+h)-f(x))/h 极限不存在",
            ),
        ],
    )
    async with SessionLocal() as db:
        from sqlalchemy import update

        await db.execute(
            update(Course).where(Course.id == course_id).values(source_pdf_path=pdf_path)
        )
        await db.commit()

    async def assess_stub(_api, _messages):
        return _assessment_payload_for(
            covered=["导数定义", "切线斜率", "可导与连续"],
            partial=[],
            untouched=[],
            difficulty="hard",
            count=7,
        )

    monkeypatch.setattr(assessor_module, "complete_json", assess_stub)

    async with SessionLocal() as db:
        a = await run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert a.suggested_difficulty == "hard"
        assert a.suggested_count == 7

    async def gen_stub(_api, _messages):
        return json.dumps(
            _exercise_payload(
                count=7,
                difficulty="hard",
                concept_per_question=[
                    "导数定义",
                    "切线斜率",
                    "可导与连续",
                    "导数定义",
                    "切线斜率",
                    "可导与连续",
                    "导数定义",
                ],
            ),
            ensure_ascii=False,
        )

    monkeypatch.setattr(materializer_module, "complete_json", gen_stub)
    result = await generate_exercise_set(
        kp_title="导数",
        pdf_path=pdf_path,
        page_start=1,
        page_end=2,
        keyphrases=KEYPHRASES,
        covered_concepts=["导数定义", "切线斜率", "可导与连续"],
        difficulty="hard",
        count=7,
    )
    assert len(result.exercises) == 7
    assert result.exercises[0].question_type == "Comparison"
    assert result.exercises[1].question_type == "Causal Consequence"
    assert result.exercises[2].question_type == "Inference"


async def test_profile_early_exit_uses_empty_assessment_fallback(
    tmp_path, monkeypatch
):
    pdf_path = _make_pdf_at(tmp_path)
    course_id, kp_id, _ = await _setup_kp_with_chat(history=[])
    async with SessionLocal() as db:
        from sqlalchemy import update

        await db.execute(
            update(Course).where(Course.id == course_id).values(source_pdf_path=pdf_path)
        )
        await db.commit()

    called = {"n": 0}

    async def assess_stub(_api, _messages):
        called["n"] += 1
        return "should not be called"

    monkeypatch.setattr(assessor_module, "complete_json", assess_stub)

    async with SessionLocal() as db:
        a = await run_assessment(kp_id=kp_id, attempt=1, db=db)
        assert called["n"] == 0
        assert a.suggested_difficulty == "easy"
        assert a.suggested_count == 2
        assert float(a.coverage_ratio) == 0.0


async def test_assessment_missing_checklist_concept_raises(tmp_path, monkeypatch):
    course_id, kp_id, _ = await _setup_kp_with_chat(
        history=[
            (MessageRole.assistant, "你对导数知道什么？"),
            (MessageRole.user, "切线斜率"),
        ],
    )

    async def assess_stub(_api, _messages):
        return json.dumps(
            {
                "covered": [{"concept": "切线斜率", "evidence": "x"}],
                "partial": [],
                "untouched": [],
                "coverage_ratio": 0.33,
                "mastery_summary": "summary",
                "suggested_difficulty": "easy",
                "suggested_count": 3,
            }
        )

    monkeypatch.setattr(assessor_module, "complete_json", assess_stub)

    async with SessionLocal() as db:
        with pytest.raises(ValueError, match="漏掉"):
            await run_assessment(kp_id=kp_id, attempt=1, db=db)


async def test_assessment_carries_across_attempt_bump(tmp_path, monkeypatch):
    """When attempt bumps (e.g. user changes count), the previous assessment
    is still findable so covered_concepts stays in scope."""
    pdf_path = _make_pdf_at(tmp_path)
    course_id, kp_id, _ = await _setup_kp_with_chat(
        history=[
            (MessageRole.assistant, "q"),
            (MessageRole.user, "a"),
        ],
    )
    async with SessionLocal() as db:
        from sqlalchemy import update

        await db.execute(
            update(Course).where(Course.id == course_id).values(source_pdf_path=pdf_path)
        )
        await db.commit()

    async def assess_stub(_api, _messages):
        return _assessment_payload_for(
            covered=["导数定义"],
            partial=["切线斜率"],
            untouched=["可导与连续"],
            difficulty="normal",
            count=4,
        )

    monkeypatch.setattr(assessor_module, "complete_json", assess_stub)

    async with SessionLocal() as db:
        await run_assessment(kp_id=kp_id, attempt=1, db=db)

    async with SessionLocal() as db:
        kp = await db.get(KnowledgePoint, kp_id)
        kp.current_attempt = 2
        await db.commit()

    async with SessionLocal() as db:
        result = await db.execute(
            select(KPAssessment)
            .where(KPAssessment.kp_id == kp_id)
            .order_by(KPAssessment.attempt.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        assert latest is not None
        assert latest.attempt == 1


@pytest.mark.asyncio
async def test_exercise_set_is_write_once_per_attempt(tmp_path, monkeypatch):
    """Regression (correct MCQ scored 0): once a (kp, attempt) exercise set
    exists, a second generation — background _spawn_tailor or a param-change
    POST /exercise-set — MUST NOT overwrite it in place. Otherwise the
    student is graded against a different set than the one they answered."""
    from app.kp.materializer import tailor_exercise_set
    from app.models import KPExerciseSet

    pdf_path = _make_pdf_at(tmp_path)
    _, kp_id, _ = await _setup_kp_with_chat(history=[])

    calls = {"n": 0}

    async def gen_stub(_api, _messages):
        calls["n"] += 1
        # both concepts are valid keyphrases so the topic whitelist passes;
        # the question text differs so an overwrite is detectable.
        concept = "导数" if calls["n"] == 1 else "极限"
        return json.dumps(
            _exercise_payload(
                count=2,
                difficulty="normal",
                concept_per_question=[concept, concept],
            ),
            ensure_ascii=False,
        )

    monkeypatch.setattr(materializer_module, "complete_json", gen_stub)

    async with SessionLocal() as db:
        first = await tailor_exercise_set(
            db, kp_id=kp_id, attempt=1, kp_title="导数",
            pdf_path=pdf_path, page_start=1, page_end=2,
            difficulty="normal", count=2,
        )
        assert first is not None
        assert "导数" in first.exercises[0]["question"]

        second = await tailor_exercise_set(
            db, kp_id=kp_id, attempt=1, kp_title="导数",
            pdf_path=pdf_path, page_start=1, page_end=2,
            difficulty="normal", count=2,
        )
        assert second is not None
        # write-once: still set A, NOT regenerated to 极限
        assert "导数" in second.exercises[0]["question"]
        assert "极限" not in second.exercises[0]["question"]

    async with SessionLocal() as db:
        row = await db.get(KPExerciseSet, (kp_id, 1))
        assert "导数" in row.exercises[0]["question"]
        assert "极限" not in row.exercises[0]["question"]
