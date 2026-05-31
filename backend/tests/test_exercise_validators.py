"""Pure validators for LLM exercise output (no DB, no LLM)."""

import pytest
from pydantic import ValidationError

from app.kp.exercise_validators import _Exercise, validate_self_contained


def _short(question: str) -> _Exercise:
    return _Exercise(
        type="short_answer",
        question_type="Application",
        question=question,
        correct_answer="参考答案",
        grading_criteria=["命中核心概念", "给出推理过程"],
    )


def test_self_contained_rejects_text_referential_stem():
    """The student learns via Socratic dialogue and never reads the PDF,
    so a stem that points at 'the text' is unanswerable."""
    exercises = [_short("根据文本，简述勾股定理的内容。")]
    with pytest.raises(ValueError, match="未读过原文|根据文本|自足"):
        validate_self_contained(exercises)


def test_self_contained_accepts_standalone_stem():
    exercises = [
        _short("直角三角形两直角边为 a、b，斜边为 c，写出三者的关系并说明理由。")
    ]
    validate_self_contained(exercises)  # no raise


def test_short_answer_requires_grading_criteria():
    """Defect #2: a short-answer with no explicit 评分要点 leaves both the
    student and the grader guessing what earns points."""
    with pytest.raises(ValidationError, match="grading_criteria"):
        _Exercise(
            type="short_answer",
            question_type="Application",
            question="说明勾股定理的几何意义。",
            correct_answer="参考答案",
        )


def test_short_answer_accepts_six_criteria():
    """Regression: a benign LLM overshoot (6 points) must NOT abort the
    whole exercise set — generation failing because the model was a bit
    verbose is worse than keeping the extra point."""
    e = _Exercise(
        type="short_answer",
        question_type="Application",
        question="写出循环体并说明其作用。",
        correct_answer="参考答案",
        grading_criteria=[f"要点{i}" for i in range(1, 7)],
    )
    assert len(e.grading_criteria) == 6


def test_short_answer_truncates_excess_criteria():
    """An unbounded list is still hygiene-capped, but by truncation, not
    by failing validation."""
    from app.kp.exercise_validators import MAX_GRADING_CRITERIA

    e = _Exercise(
        type="short_answer",
        question_type="Application",
        question="说明递归终止条件。",
        correct_answer="参考答案",
        grading_criteria=[f"要点{i}" for i in range(1, 21)],
    )
    assert len(e.grading_criteria) == MAX_GRADING_CRITERIA


def test_mcq_must_not_carry_grading_criteria():
    """MCQ is scored deterministically against correct_answer; a rubric on
    it is meaningless and signals a malformed payload."""
    with pytest.raises(ValidationError, match="grading_criteria"):
        _Exercise(
            type="mcq",
            question_type="Definition",
            question="勾股定理是？",
            options=[
                {"label": "A", "text": "a"},
                {"label": "B", "text": "b"},
                {"label": "C", "text": "c"},
                {"label": "D", "text": "d"},
            ],
            correct_answer="A",
            grading_criteria=["不该出现"],
        )
