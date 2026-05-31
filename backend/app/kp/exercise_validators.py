"""Pydantic schemas + structural validators for LLM exercise output.

Schemas (`KPMaterialPayload`, `ExerciseSetPayload`) describe what the LLM
must return. Validators enforce constraints that pydantic field rules
can't express (count-dependent layouts, topic whitelist, difficulty-mode
type locks).

Pure functions: no DB, no LLM. The materializer wires these to the LLM
call site; tests can import them directly.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

from app.kp.exercise_layout import layout, scaled_difficulty_mix


# ---------- Pydantic schemas ----------


MAX_GRADING_CRITERIA = 8


class _MCQOption(BaseModel):
    label: str = Field(..., pattern=r"^[ABCD]$")
    text: str = Field(..., min_length=1)


class _Exercise(BaseModel):
    type: str = Field(..., pattern=r"^(mcq|short_answer)$")
    question_type: str = Field(..., min_length=1, max_length=64)
    question: str = Field(..., min_length=1)
    options: list[_MCQOption] | None = None
    correct_answer: str = Field(..., min_length=1)
    # short_answer only: explicit, student-visible scoring points. Drives
    # grading (key-point coverage) instead of vibe-similarity to the lone
    # reference answer — fixes "给分标准不明确" and de-risks unfair wrongs.
    grading_criteria: list[str] | None = None

    @model_validator(mode="after")
    def _grading_criteria_matches_type(self) -> "_Exercise":
        if self.type == "short_answer":
            crit = self.grading_criteria
            if not crit or not all(c and c.strip() for c in crit):
                raise ValueError(
                    "short_answer 必须提供非空 grading_criteria（评分要点）"
                )
            # ≥1 is the real contract. The upper bound is hygiene only —
            # truncate a verbose LLM rather than abort the whole set
            # (a benign overshoot must not fail exercise generation).
            if len(crit) > MAX_GRADING_CRITERIA:
                self.grading_criteria = crit[:MAX_GRADING_CRITERIA]
        elif self.grading_criteria is not None:
            raise ValueError("mcq 不应携带 grading_criteria")
        return self


class _ChecklistItem(BaseModel):
    concept: str = Field(..., min_length=1, max_length=40)
    description: str = Field(..., min_length=1, max_length=200)
    must_anchor: bool = False


class KPMaterialPayload(BaseModel):
    """Validated KP material output from the LLM."""

    layer3_prompt: str = Field(..., min_length=10)
    keyphrases: list[str] = Field(..., min_length=3, max_length=5)
    knowledge_checklist: list[_ChecklistItem] = Field(..., min_length=3, max_length=7)

    @model_validator(mode="after")
    def _at_least_two_must_anchor(self) -> "KPMaterialPayload":
        anchor_count = sum(1 for item in self.knowledge_checklist if item.must_anchor)
        if anchor_count < 2:
            raise ValueError(
                f"knowledge_checklist 必须至少包含 2 项 must_anchor=true 的概念，"
                f"实得 {anchor_count} 项"
            )
        return self


class ExerciseSetPayload(BaseModel):
    """Validated exercise set output from the LLM."""

    exercises: list[_Exercise] = Field(..., min_length=2, max_length=7)


# ---------- Structural validators ----------


def validate_layout(
    exercises: list[_Exercise],
    *,
    count: int = 5,
    difficulty: str = "normal",
) -> None:
    """Enforce count, type sequence, mcq option shape, distinct-mcq-types rule."""
    expected = layout(count)
    if len(exercises) != count:
        raise ValueError(
            f"题量错误，期望 {count} 道，实得 {len(exercises)} 道"
        )
    actual = [e.type for e in exercises]
    if actual != expected:
        raise ValueError(
            f"题型布局错误，期望 {expected}，实得 {actual}"
        )
    for i, e in enumerate(exercises):
        if e.type == "mcq":
            if not e.options or len(e.options) != 4:
                raise ValueError(f"第 {i + 1} 道 mcq 必须有 4 个 options")
            labels = sorted(o.label for o in e.options)
            if labels != ["A", "B", "C", "D"]:
                raise ValueError(
                    f"第 {i + 1} 道 mcq option labels 必须为 A/B/C/D，实得 {labels}"
                )
            if e.correct_answer not in {"A", "B", "C", "D"}:
                raise ValueError(
                    f"第 {i + 1} 道 mcq correct_answer 必须为 A/B/C/D 之一，"
                    f"实得 {e.correct_answer!r}"
                )
        else:
            if e.options:
                raise ValueError(f"第 {i + 1} 道 short_answer 不应携带 options")
    if difficulty == "normal":
        mcqs = [e for e in exercises if e.type == "mcq"]
        if len(mcqs) >= 2:
            qtypes = [e.question_type for e in mcqs]
            if len(set(qtypes)) != len(qtypes):
                raise ValueError(
                    f"{len(mcqs)} 道 mcq 题型必须互不相同，实得 {qtypes}"
                )


# Phrases that assume the student has the source passage in front of
# them. The learning surface is the Socratic dialogue — the student never
# reads the PDF — so a stem pointing at "the text/passage/author" is
# unanswerable. The generator must inline whatever it needs into the stem.
_TEXT_REFERENTIAL = re.compile(
    r"根据(上述|本|该|原|这篇|此)?(文本|原文|文章|课文|短文|选段|选文|"
    r"文段|段落|篇章|材料|文献|内容|资料)"
    r"|(文本|原文|文章|课文|短文|选段|选文|文段|材料|文献)中"
    r"|(上文|下文|前文|文中|本文|此文)"
    r"|作者(认为|指出|提到|强调|所说|的观点|想要|主张)"
    r"|(阅读|结合|依据|参照)(上述|本|该|这篇)?(材料|文本|原文|文章|选段|短文)"
    r"|文中(提到|所述|指出|说|描述|强调)"
)


def validate_self_contained(exercises: list[_Exercise]) -> None:
    """Reject stems that reference an unseen source passage.

    The student learns via dialogue and never sees the PDF; a question
    that says 「根据文本」「文中提到」「作者认为」 is unanswerable. Stems
    must be self-contained (自足) — inline any needed givens.
    """
    for i, e in enumerate(exercises):
        m = _TEXT_REFERENTIAL.search(e.question)
        if m is not None:
            raise ValueError(
                f"第 {i + 1} 道题的题干引用了学生未读过原文（命中 {m.group(0)!r}）；"
                f"题干必须自足，不得出现「根据文本/文中/作者…」类指向。"
                f"题干：{e.question[:60]!r}"
            )


def validate_topic_whitelist(
    exercises: list[_Exercise],
    *,
    covered_concepts: list[str],
) -> None:
    """Each question stem must mention ≥1 concept from the whitelist."""
    if not covered_concepts:
        return
    for i, e in enumerate(exercises):
        if not any(c in e.question for c in covered_concepts):
            raise ValueError(
                f"第 {i + 1} 道题的题干未提及考察范围中的任何概念。"
                f"题干：{e.question[:60]!r}；范围：{covered_concepts}"
            )


def validate_difficulty_types(
    exercises: list[_Exercise],
    *,
    difficulty: str,
    count: int = 5,
) -> None:
    """Easy/hard mode locks question_type per slot. Normal is a no-op."""
    mix = scaled_difficulty_mix(difficulty, count)
    if not mix["mcq"]:
        return
    expected = list(mix["mcq"]) + list(mix["short_answer"])
    if len(expected) != count:
        raise RuntimeError(
            f"internal: difficulty mix length {len(expected)} != count {count}"
        )
    for i, e in enumerate(exercises):
        if e.question_type != expected[i]:
            raise ValueError(
                f"难度档 {difficulty} 要求第 {i + 1} 道题型为 {expected[i]!r}，"
                f"实得 {e.question_type!r}"
            )
