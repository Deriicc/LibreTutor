import json
import uuid
from typing import Any

import pytest
from sqlalchemy import delete

from app.db import SessionLocal
from app.kp import grader
from app.models import (
    Chapter,
    Course,
    GenerationStatus,
    Grade,
    KnowledgePoint,
    KPExerciseSet,
    Section,
    Submission,
    SubmissionStatus,
)


def _fixture_exercises() -> list[dict[str, Any]]:
    """5 exercises: 3 MCQ (correct A/B/C) + 2 short-answer."""
    return [
        {
            "type": "mcq",
            "question_type": "Definition",
            "question": "Q1?",
            "options": [
                {"label": "A", "text": "right"},
                {"label": "B", "text": "wrong"},
                {"label": "C", "text": "wrong"},
                {"label": "D", "text": "wrong"},
            ],
            "correct_answer": "A",
        },
        {
            "type": "mcq",
            "question_type": "Comparison",
            "question": "Q2?",
            "options": [
                {"label": "A", "text": "wrong"},
                {"label": "B", "text": "right"},
                {"label": "C", "text": "wrong"},
                {"label": "D", "text": "wrong"},
            ],
            "correct_answer": "B",
        },
        {
            "type": "mcq",
            "question_type": "Application",
            "question": "Q3?",
            "options": [
                {"label": "A", "text": "wrong"},
                {"label": "B", "text": "wrong"},
                {"label": "C", "text": "right"},
                {"label": "D", "text": "wrong"},
            ],
            "correct_answer": "C",
        },
        {
            "type": "short_answer",
            "question_type": "Inference",
            "question": "Q4?",
            "correct_answer": "ref4",
            "grading_criteria": ["要点4a", "要点4b"],
        },
        {
            "type": "short_answer",
            "question_type": "Application",
            "question": "Q5?",
            "correct_answer": "ref5",
            "grading_criteria": ["要点5a"],
        },
    ]


def _stub_llm_payload(short_score: int = 75) -> dict[str, Any]:
    """LLM response — note MCQ scores in here will be overridden by deterministic check."""
    return {
        "per_question": [
            {"index": 0, "score": 50, "feedback": "fb0"},  # MCQ — score will be overridden
            {"index": 1, "score": 50, "feedback": "fb1"},
            {"index": 2, "score": 50, "feedback": "fb2"},
            {"index": 3, "score": short_score, "feedback": "fb3"},
            {"index": 4, "score": short_score, "feedback": "fb4"},
        ],
        "overall_feedback": "整体不错",
    }


# ---------- pure-function tests ----------


def test_grade_schema_accepts_valid_payload():
    parsed = grader._GradeSchema.model_validate(_stub_llm_payload())
    assert len(parsed.per_question) == 5
    assert parsed.overall_feedback == "整体不错"


def test_validate_indices_rejects_wrong_count():
    """Schema now allows length [2,7]; the count check moved to _validate_indices."""
    parsed = grader._GradeSchema.model_validate(_stub_llm_payload())
    # 5 items but we say expected count = 4 → raises
    with pytest.raises(ValueError, match="per_question length"):
        grader._validate_indices(parsed.per_question, count=4)


def test_validate_indices_rejects_bad_indices():
    bad = _stub_llm_payload()
    bad["per_question"][0]["index"] = 99
    parsed = grader._GradeSchema.model_validate(bad)
    with pytest.raises(ValueError, match="indices"):
        grader._validate_indices(parsed.per_question, count=5)


def test_grade_schema_rejects_score_above_100():
    bad = _stub_llm_payload()
    bad["per_question"][0]["score"] = 150
    with pytest.raises(Exception):
        grader._GradeSchema.model_validate(bad)


def test_build_grading_user_msg_includes_all_fields():
    exs = _fixture_exercises()
    answers = {0: "A", 1: "X", 3: "学生答 4"}
    msg = grader._build_grading_user_msg(exs, answers)
    # N-prefix tells the LLM the count explicitly, blocking the
    # stale-prompt regression where it always returned 5 entries.
    assert "本次共 5 道题" in msg
    assert "per_question 必须有 5 项" in msg
    assert "indices 严格为 0..4" in msg
    assert "第 1 题" in msg and "Q1?" in msg
    assert "参考答案（选项）：A" in msg
    assert "学生答案：A" in msg          # q0
    assert "学生答案：X" in msg          # q1
    assert "学生答案：（未作答）" in msg  # q2 missing
    assert "学生答案：学生答 4" in msg    # short answer q3


def test_build_grading_user_msg_includes_grading_criteria():
    """Defect #2/#3: the grader must see each short-answer's explicit
    评分要点 so it scores by key-point coverage, not vibe-similarity to
    the lone reference answer."""
    exs = _fixture_exercises()
    msg = grader._build_grading_user_msg(exs, {})
    assert "评分要点" in msg
    assert "要点4a" in msg and "要点4b" in msg
    assert "要点5a" in msg


def test_build_grading_user_msg_omits_criteria_when_absent():
    """Back-compat: exercise sets stored before the rubric existed have
    no grading_criteria — the builder must not crash or emit an empty
    评分要点 header for them."""
    legacy = [
        {
            "type": "short_answer",
            "question_type": "Inference",
            "question": "老题?",
            "correct_answer": "旧参考答案",
        },
    ]
    msg = grader._build_grading_user_msg(legacy, {0: "ans"})
    assert "评分要点" not in msg
    assert "老题?" in msg


def test_build_grading_user_msg_two_question_set():
    """When assessor suggests count=2, prefix must reflect that so the
    LLM doesn't emit a 5-entry per_question (the live bug Issue 4)."""
    exs = _fixture_exercises()[:2]  # 2 mcq, no short_answer in this slice
    msg = grader._build_grading_user_msg(exs, {0: "A", 1: "B"})
    assert "本次共 2 道题" in msg
    assert "mcq 2 + short_answer 0" in msg
    assert "per_question 必须有 2 项" in msg
    assert "indices 严格为 0..1" in msg


async def test_call_llm_grade_rejects_wrong_count_then_retries(monkeypatch):
    """Grader must reject a 5-entry payload when only 2 exercises were
    sent, then accept the retry with the right count."""
    calls = {"n": 0}

    async def stub(_api, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            # First attempt: LLM ignores the N-prefix and returns 5
            return json.dumps(_stub_llm_payload())
        # Retry: correct 2-entry response
        return json.dumps(
            {
                "per_question": [
                    {"index": 0, "score": 100, "feedback": "ok"},
                    {"index": 1, "score": 0, "feedback": "no"},
                ],
                "overall_feedback": "fine",
            }
        )

    monkeypatch.setattr(grader, "complete_json", stub)
    exs = _fixture_exercises()[:2]
    out = await grader._call_llm_grade(exs, {0: "A", 1: "B"})
    assert calls["n"] == 2
    assert len(out.per_question) == 2


def test_override_mcq_scores_correct_gets_100_wrong_gets_0():
    exs = _fixture_exercises()
    answers = {0: "A", 1: "C", 2: "C", 3: "学生", 4: ""}  # q1 wrong, q2 right
    payload = _stub_llm_payload(short_score=80)
    parsed = grader._GradeSchema.model_validate(payload)
    out = grader._override_mcq_scores(exs, answers, parsed.per_question)
    by_idx = {q["index"]: q["score"] for q in out}
    assert by_idx[0] == 100  # MCQ correct
    assert by_idx[1] == 0    # MCQ wrong
    assert by_idx[2] == 100  # MCQ correct
    assert by_idx[3] == 80   # short — uses LLM score
    assert by_idx[4] == 80


def test_override_mcq_handles_missing_or_empty_answer():
    exs = _fixture_exercises()
    answers = {0: "", 3: "ans"}  # q0 empty (wrong), q1/q2 missing (wrong), q4 missing (LLM keeps)
    payload = _stub_llm_payload(short_score=60)
    parsed = grader._GradeSchema.model_validate(payload)
    out = grader._override_mcq_scores(exs, answers, parsed.per_question)
    by_idx = {q["index"]: q["score"] for q in out}
    assert by_idx[0] == 0  # empty != "A"
    assert by_idx[1] == 0
    assert by_idx[2] == 0
    assert by_idx[3] == 60  # short — LLM keeps
    assert by_idx[4] == 60


async def test_call_llm_grade_retries_once_on_bad_output(monkeypatch):
    calls = {"n": 0}

    async def stub(_api, _messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"per_question": [], "overall_feedback": "x"})  # too few
        return json.dumps(_stub_llm_payload())

    monkeypatch.setattr(grader, "complete_json", stub)
    out = await grader._call_llm_grade(_fixture_exercises(), {0: "A"})
    assert calls["n"] == 2
    assert len(out.per_question) == 5


async def test_call_llm_grade_raises_after_retry_exhausted(monkeypatch):
    async def stub(_api, _messages):
        return "not-json"

    monkeypatch.setattr(grader, "complete_json", stub)
    with pytest.raises(ValueError, match="评分 LLM 输出不合规"):
        await grader._call_llm_grade(_fixture_exercises(), {0: "A"})


# ---------- integration test (real PG, single test to avoid asyncpg loop reuse) ----------


async def _setup_fixture_kp() -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        course = Course(
            name="grader test",
            source_pdf_path="/tmp/grader_test.pdf",
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
            section_id=section.id, title="kp", order_index=0, boundary={}
        )
        db.add(kp)
        await db.flush()
        db.add(
            KPExerciseSet(
                kp_id=kp.id,
                attempt=1,
                exercises=_fixture_exercises(),
            )
        )
        await db.commit()
        return course.id, kp.id


async def _cleanup_fixture_kp(course_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(Course).where(Course.id == course_id))
        await db.commit()


async def test_grade_submission_full_state_machine_and_failure_path(monkeypatch):
    """One integration test covers happy path + failure path (separate tests
    trip an asyncpg connection-pool / event-loop reuse issue under
    pytest-asyncio function-scoped fixtures)."""
    course_id, kp_id = await _setup_fixture_kp()
    try:
        # --- HAPPY PATH ---
        async def stub_ok(_api, _messages):
            return json.dumps(_stub_llm_payload(short_score=70))

        monkeypatch.setattr(grader, "complete_json", stub_ok)

        answers = [
            {"index": 0, "answer": "A"},   # MCQ correct
            {"index": 1, "answer": "X"},   # MCQ wrong
            {"index": 2, "answer": "C"},   # MCQ correct
            {"index": 3, "answer": "学生答 4"},
            {"index": 4, "answer": "学生答 5"},
        ]

        async with SessionLocal() as db:
            sub_ok = Submission(
                kp_id=kp_id,
                answers=answers,
                status=SubmissionStatus.pending,
            )
            db.add(sub_ok)
            await db.commit()
            sub_ok_id = sub_ok.id
            assert sub_ok.status == SubmissionStatus.pending  # before run

        await grader.grade_submission(sub_ok_id)

        async with SessionLocal() as db:
            final = await db.get(Submission, sub_ok_id)
            assert final is not None
            assert final.status == SubmissionStatus.done
            assert final.completed_at is not None
            assert final.error is None

            grade = await db.get(Grade, sub_ok_id)
            assert grade is not None
            scores = {q["index"]: q["score"] for q in grade.per_question}
            assert scores[0] == 100   # MCQ correct, deterministic
            assert scores[1] == 0     # MCQ wrong, deterministic
            assert scores[2] == 100   # MCQ correct, deterministic
            assert scores[3] == 70    # short — LLM score kept
            assert scores[4] == 70
            # Weighted: MCQ weight=1, short_answer weight=2.
            # (100+0+100)*1 + (70+70)*2 = 200 + 280 = 480; sum_w = 3 + 4 = 7
            # → 480 / 7 ≈ 68.57 → round to 69
            assert grade.overall_score == 69
            assert grade.overall_feedback == "整体不错"

        # --- FAILURE PATH ---
        async def stub_bad(_api, _messages):
            return "not-json"

        monkeypatch.setattr(grader, "complete_json", stub_bad)

        async with SessionLocal() as db:
            sub_bad = Submission(
                kp_id=kp_id,
                answers=[{"index": i, "answer": "A"} for i in range(5)],
                status=SubmissionStatus.pending,
            )
            db.add(sub_bad)
            await db.commit()
            sub_bad_id = sub_bad.id

        with pytest.raises(ValueError):
            await grader.grade_submission(sub_bad_id)

        async with SessionLocal() as db:
            failed = await db.get(Submission, sub_bad_id)
            assert failed is not None
            assert failed.status == SubmissionStatus.failed
            assert failed.error and "评分" in failed.error
            assert await db.get(Grade, sub_bad_id) is None
    finally:
        await _cleanup_fixture_kp(course_id)
