"""ExerciseGrader — single-LLM-call rubric scoring with deterministic MCQ override.

Flow:
  1. Submission row written by API handler in `pending` state.
  2. Background task calls grade_submission(submission_id):
     - flips status to running
     - pulls KP exercises (from KPLoader cache) and student answers
     - runs one LLM JSON-mode call to score every question + write feedback
     - overrides MCQ scores with deterministic 0/100 vs correct_answer
     - writes Grade row, flips status to done (or failed on error)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.db import SessionLocal
from app.kp.decider import record_grading_weakness_if_low
from app.llm import complete_json
from app.user_llm import load_api_settings
from app.models import (
    Grade,
    KPExerciseSet,
    Submission,
    SubmissionStatus,
)

logger = logging.getLogger(__name__)


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "exercise_grading.md"
GRADING_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


# Per-type weights for the overall_score average. MCQ is deterministic
# 0/100, so a single MCQ slip can swing the unweighted mean by 20 points
# in a 5-question set — disproportionate to its informational value.
# Short-answer scores are continuous (0-100) and carry richer evidence
# of mastery, so we weight them double.
_GRADE_WEIGHTS: dict[str, int] = {"mcq": 1, "short_answer": 2}


# ---------- LLM IO schema ----------


class _PerQuestionGrade(BaseModel):
    index: int = Field(..., ge=0)
    score: int = Field(..., ge=0, le=100)
    feedback: str = Field(..., min_length=1, max_length=2000)


class _GradeSchema(BaseModel):
    # Length matches the exercise set (variable, [2, 7]); enforced
    # programmatically against the actual count by _validate_indices.
    per_question: list[_PerQuestionGrade] = Field(..., min_length=2, max_length=7)
    overall_feedback: str = Field(..., min_length=1, max_length=2000)


def _validate_indices(per_question: list[_PerQuestionGrade], *, count: int) -> None:
    if len(per_question) != count:
        raise ValueError(
            f"per_question length must equal exercise count {count}, "
            f"got {len(per_question)}"
        )
    idxs = sorted(p.index for p in per_question)
    if idxs != list(range(count)):
        raise ValueError(
            f"per_question indices must be 0..{count - 1}, got {idxs}"
        )


# ---------- LLM call ----------


def _build_grading_user_msg(
    exercises: list[dict[str, Any]],
    answers_by_index: dict[int, str],
) -> str:
    count = len(exercises)
    n_mcq = sum(1 for ex in exercises if ex["type"] == "mcq")
    n_short = sum(1 for ex in exercises if ex["type"] == "short_answer")
    lines: list[str] = [
        f"本次共 {count} 道题（mcq {n_mcq} + short_answer {n_short}）。",
        f"per_question 必须有 {count} 项，indices 严格为 0..{count - 1}。",
        "",
    ]
    for i, ex in enumerate(exercises):
        lines.append(f"## 第 {i + 1} 题（index={i}, 类型={ex['type']}, 题型={ex.get('question_type', '?')}）")
        lines.append(f"题干：{ex['question']}")
        if ex["type"] == "mcq" and ex.get("options"):
            for opt in ex["options"]:
                lines.append(f"  {opt['label']}. {opt['text']}")
            lines.append(f"参考答案（选项）：{ex['correct_answer']}")
        else:
            lines.append(f"参考答案：{ex['correct_answer']}")
            criteria = ex.get("grading_criteria") or []
            if criteria:
                lines.append("评分要点（按命中比例给分，下同）：")
                for j, c in enumerate(criteria, 1):
                    lines.append(f"  {j}. {c}")
        student = answers_by_index.get(i, "（未作答）")
        lines.append(f"学生答案：{student}")
        lines.append("")
    return "\n".join(lines)


async def _call_llm_grade(
    exercises: list[dict[str, Any]],
    answers_by_index: dict[int, str],
    api_settings: dict | None = None,
    *,
    max_retries: int = 1,
) -> _GradeSchema:
    user_msg = _build_grading_user_msg(exercises, answers_by_index)
    messages = [
        {"role": "system", "content": GRADING_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    count = len(exercises)

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = await complete_json(api_settings, messages)
            data = json.loads(raw)
            parsed = _GradeSchema.model_validate(data)
            _validate_indices(parsed.per_question, count=count)
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_err = exc
            logger.warning(
                "Grader LLM output invalid (attempt %s/%s): %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )
            continue
    raise ValueError(f"评分 LLM 输出不合规：{last_err}")


def _override_mcq_scores(
    exercises: list[dict[str, Any]],
    answers_by_index: dict[int, str],
    llm_per_question: list[_PerQuestionGrade],
) -> list[dict[str, Any]]:
    """For MCQ entries, ignore the LLM's score and use deterministic 0/100."""
    by_idx = {p.index: p for p in llm_per_question}
    out: list[dict[str, Any]] = []
    for i, ex in enumerate(exercises):
        llm_grade = by_idx.get(i)
        feedback = llm_grade.feedback if llm_grade is not None else ""
        if ex["type"] == "mcq":
            student = (answers_by_index.get(i) or "").strip().upper()
            score = 100 if student == ex["correct_answer"] else 0
        else:
            score = llm_grade.score if llm_grade is not None else 0
        out.append({"index": i, "score": score, "feedback": feedback})
    return out


# ---------- Orchestration ----------


async def grade_submission(submission_id: uuid.UUID) -> None:
    """Grade a Submission end-to-end. Owns its own DB session."""
    async with SessionLocal() as db:
        submission = await db.get(Submission, submission_id)
        if submission is None:
            logger.warning("grade_submission: submission %s not found", submission_id)
            return
        if submission.status != SubmissionStatus.pending:
            logger.info(
                "grade_submission: submission %s status is %s, skipping",
                submission_id,
                submission.status,
            )
            return

        submission.status = SubmissionStatus.running
        await db.commit()

        try:
            # Pin to the attempt this submission was answering, so a retry
            # that bumped current_attempt doesn't switch the grader to a
            # freshly-generated, different exercise set.
            exercise_set = await db.get(
                KPExerciseSet, (submission.kp_id, submission.attempt)
            )
            if exercise_set is None:
                raise ValueError("练习集不存在；请先访问该 KP 的作业页生成内容")

            exercises = list(exercise_set.exercises)
            count = len(exercises)
            if count < 2 or count > 7:
                raise ValueError(
                    f"KP 题目数应在 [2, 7] 范围，实际 {count}"
                )

            raw_answers = list(submission.answers)
            answers_by_index: dict[int, str] = {}
            for entry in raw_answers:
                idx = int(entry.get("index"))
                ans = str(entry.get("answer", "")).strip()
                if 0 <= idx < count:
                    answers_by_index[idx] = ans

            api_settings = await load_api_settings(db)
            llm_grade = await _call_llm_grade(
                exercises, answers_by_index, api_settings
            )
            per_question = _override_mcq_scores(
                exercises, answers_by_index, llm_grade.per_question
            )
            weighted_sum = sum(
                q["score"] * _GRADE_WEIGHTS.get(ex["type"], 1)
                for q, ex in zip(per_question, exercises)
            )
            weight_total = sum(
                _GRADE_WEIGHTS.get(ex["type"], 1) for ex in exercises
            )
            overall_score = round(weighted_sum / weight_total)

            grade = Grade(
                submission_id=submission_id,
                per_question=per_question,
                overall_score=overall_score,
                overall_feedback=llm_grade.overall_feedback,
            )
            db.add(grade)

            await record_grading_weakness_if_low(
                db,
                kp_id=submission.kp_id,
                overall_score=overall_score,
            )

            submission.status = SubmissionStatus.done
            submission.completed_at = datetime.now(tz=timezone.utc)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("grade_submission failed for %s", submission_id)
            await db.rollback()
            failed = await db.get(Submission, submission_id)
            if failed is not None:
                failed.status = SubmissionStatus.failed
                failed.error = str(exc)[:1000]
                failed.completed_at = datetime.now(tz=timezone.utc)
                await db.commit()
            raise
