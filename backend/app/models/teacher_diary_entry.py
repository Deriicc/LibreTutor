"""TeacherDiaryEntry — the teacher's first-person, in-character diary
reflection for one (kp_id, attempt).

Written at KP end (advance next/retry) by the live persona of that
moment, signed by it. retry produces a new entry; old entries (and
their signatures) are immutable — the diary book is a chronological,
possibly multi-author timeline. See ADR-0023 + CONTEXT.md.

Row is created `pending` when generation is spawned so the book can
show a placeholder and the reaper can backfill failures; flipped to
`done` (body/signature/label filled) or `failed` (error filled).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DiaryStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class TeacherDiaryEntry(Base):
    __tablename__ = "teacher_diary_entries"

    kp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempt: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1, server_default="1"
    )
    # Denormalized for course-scoped chronological queries (same pattern
    # as Weakness.course_id).
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null until generation succeeds.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[DiaryStatus] = mapped_column(
        SAEnum(
            DiaryStatus,
            name="diary_status",
            native_enum=False,
            length=16,
        ),
        nullable=False,
        default=DiaryStatus.pending,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "next" | "retry" — how the attempt ended. Persisted so the reaper
    # can re-spawn a failed/pending entry without re-deriving it.
    ended_by: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="next"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
