"""KPExerciseSet — dialogue-tailored exercise set for one (KP, attempt).

Generated after the assessor produces a KPAssessment, using:
- The KPMaterial's checklist + keyphrases (PDF-derived coverage map)
- The assessment's covered + partial concepts (what was actually discussed)
- The assessment's suggested difficulty + count

Retry bumps `KnowledgePoint.current_attempt`; the next assessor cycle writes
a new row at the new attempt. Past attempts stay so diary/report helpers can
render the questions a past Submission actually saw. Weakness review
injection was removed; exercise generation is scoped to the current KP and
attempt.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KPExerciseSet(Base):
    __tablename__ = "kp_exercise_sets"

    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempt: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1, server_default="1"
    )
    exercises: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Generation params: needed so POST /exercise-set can short-circuit when
    # the requested params match what's already cached.
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="normal"
    )
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="5"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
