"""KPAssessment — coverage / mastery snapshot computed from a chat history.

One row per (kp_id, attempt). Re-running assessment on the same attempt
overwrites the row (the latest snapshot is what we want). Bumping the KP's
current_attempt (retry) starts a fresh assessment at the new attempt number,
mirroring how KPExerciseSet is keyed.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KPAssessment(Base):
    __tablename__ = "kp_assessments"

    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempt: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1, server_default="1"
    )
    # Each list element shape:
    #   covered/partial: {"concept": str, "evidence": str}
    #   untouched:       {"concept": str, "reason": str}
    covered: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    partial: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    untouched: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Stored as Numeric(3,2) so 0.72 round-trips cleanly. We could re-derive
    # it from covered/partial counts, but persisting the LLM's reported value
    # lets us audit later if the math doesn't match.
    coverage_ratio: Mapped[float] = mapped_column(
        Numeric(3, 2), nullable=False, default=0.0
    )
    mastery_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggested_difficulty: Mapped[str] = mapped_column(
        String(8), nullable=False, default="normal"
    )
    suggested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
