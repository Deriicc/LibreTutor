"""KPMaterial — PDF-derived teaching material for one KP.

Generated once when the course is built (or lazily on first KP visit). Stable
across dialogue attempts: the same checklist + keyphrases + layer3 hint is
read by the chat dialogue (Layer 3) and by the assessor.

Distinct from KPExerciseSet, which is dialogue-tailored and re-generated per
attempt after the assessor runs.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KPMaterial(Base):
    __tablename__ = "kp_materials"

    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )
    layer3_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    keyphrases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    knowledge_checklist: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # DEPRECATED (ADR-0023, supersedes ADR-0020): persona is now rendered
    # live every chat turn, never snapshotted. No longer written; existing
    # rows keep stale values, new rows are NULL. Column retained to avoid a
    # destructive migration; drop in a future cleanup migration.
    layer2_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
