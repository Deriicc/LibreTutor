import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models import SubmissionStatus


class KPContentOut(BaseModel):
    kp_id: uuid.UUID
    layer3_prompt: str
    keyphrases: list[str]
    exercises: list[dict[str, Any]]
    difficulty: str
    count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AnswerIn(BaseModel):
    index: int = Field(..., ge=0, le=6)
    answer: str = Field(..., max_length=4000)


class SubmitIn(BaseModel):
    """Task 7 widened to [2, 7]. The cross-check that indices form a
    contiguous 0..N-1 set is done in the route handler against the actual
    kp_content's exercise count, since pydantic field_validator can't
    access the kp_content row."""

    answers: list[AnswerIn] = Field(..., min_length=2, max_length=7)

    @field_validator("answers")
    @classmethod
    def _indices_form_dense_set(cls, v: list[AnswerIn]) -> list[AnswerIn]:
        idxs = sorted(a.index for a in v)
        n = len(idxs)
        if idxs != list(range(n)):
            raise ValueError(
                f"answers must have indices 0..{n - 1} exactly once each"
            )
        return v


class SubmissionOut(BaseModel):
    id: uuid.UUID
    kp_id: uuid.UUID
    status: SubmissionStatus
    error: str | None = None
    submitted_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PerQuestionGradeOut(BaseModel):
    index: int
    score: int
    feedback: str


class GradeOut(BaseModel):
    per_question: list[PerQuestionGradeOut]
    overall_score: int
    overall_feedback: str

    model_config = {"from_attributes": True}


class SubmissionResultOut(BaseModel):
    submission: SubmissionOut
    grade: GradeOut | None = None
    suggestion: str | None = None


class AdvanceIn(BaseModel):
    action: str = Field(..., pattern=r"^(next|retry)$")


class AdvanceOut(BaseModel):
    action: str
    kp_status: str

    @field_validator("kp_status", mode="before")
    @classmethod
    def _stringify_status(cls, v: object) -> object:
        # accept both KPStatus enum and string
        return getattr(v, "value", v)


# ---------- Assessment (Task 3) ----------


class _CoveredOut(BaseModel):
    concept: str
    evidence: str


class _PartialOut(BaseModel):
    concept: str
    evidence: str


class _UntouchedOut(BaseModel):
    concept: str
    reason: str


class AssessmentOut(BaseModel):
    kp_id: uuid.UUID
    attempt: int
    covered: list[_CoveredOut]
    partial: list[_PartialOut]
    untouched: list[_UntouchedOut]
    coverage_ratio: float
    mastery_summary: str
    suggested_difficulty: str
    suggested_count: int
    created_at: datetime

    @field_validator("coverage_ratio", mode="before")
    @classmethod
    def _decimal_to_float(cls, v: object) -> object:
        # SQLAlchemy returns Numeric as Decimal; FastAPI happily serializes it
        # but pydantic's float type expects an actual float.
        if v is None:
            return v
        return float(v)

    model_config = {"from_attributes": True}
