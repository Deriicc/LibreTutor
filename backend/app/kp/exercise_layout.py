"""Exercise set layout: count → question type sequence + difficulty mix.

Pure functions and constants. No LLM, no DB. Independently testable.

Used by:
- `exercise_validators._validate_layout` (verifying LLM output)
- `materializer.generate_exercise_set` (telling the LLM what to produce)
- Test fixtures (producing valid layouts to feed validators)
"""

from __future__ import annotations


COUNT_RANGE = (2, 7)


# Difficulty → Pro-QuEST question-type distribution by slot index.
#   - "easy":   Definition / Example / Application — recall and recognition
#   - "normal": LLM picks freely (any 3 distinct types for MCQ)
#   - "hard":   Comparison / Causal Consequence / Contradiction Resolution —
#              cross-concept reasoning
# 'normal' has empty lists meaning "no per-slot lock; the existing
# distinct-types-for-MCQ rule still applies".
DIFFICULTY_TYPE_MIX: dict[str, dict[str, list[str]]] = {
    "easy": {
        "mcq": ["Definition", "Example", "Application"],
        "short_answer": ["Application", "Application"],
    },
    "normal": {
        "mcq": [],
        "short_answer": [],
    },
    "hard": {
        "mcq": ["Comparison", "Causal Consequence", "Inference"],
        "short_answer": ["Contradiction Resolution", "Application"],
    },
}


def layout(count: int) -> list[str]:
    """Return the type sequence for the requested question count."""
    lo, hi = COUNT_RANGE
    if count < lo or count > hi:
        raise ValueError(f"count must be in [{lo}, {hi}], got {count}")

    base: dict[int, list[str]] = {
        2: ["mcq", "short_answer"],
        3: ["mcq", "mcq", "short_answer"],
        4: ["mcq", "mcq", "short_answer", "short_answer"],
        5: ["mcq", "mcq", "mcq", "short_answer", "short_answer"],
        6: ["mcq", "mcq", "mcq", "mcq", "short_answer", "short_answer"],
        7: ["mcq", "mcq", "mcq", "mcq", "short_answer", "short_answer", "short_answer"],
    }
    return list(base[count])


def scaled_difficulty_mix(difficulty: str, count: int) -> dict[str, list[str]]:
    """Scale DIFFICULTY_TYPE_MIX to match the actual mcq / short_answer
    slot count in the count-N layout. Padding repeats the last type."""
    base = DIFFICULTY_TYPE_MIX.get(difficulty)
    if base is None or not base["mcq"]:
        return {"mcq": [], "short_answer": []}
    seq = layout(count)
    n_mcq = sum(1 for t in seq if t == "mcq")
    n_short = sum(1 for t in seq if t == "short_answer")

    def fit(lst: list[str], n: int) -> list[str]:
        if n <= len(lst):
            return lst[:n]
        return lst + [lst[-1]] * (n - len(lst))

    return {
        "mcq": fit(base["mcq"], n_mcq),
        "short_answer": fit(base["short_answer"], n_short),
    }
