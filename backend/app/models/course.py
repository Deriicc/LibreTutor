import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GenerationStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(String(512), nullable=False)
    generation_status: Mapped[GenerationStatus] = mapped_column(
        SAEnum(
            GenerationStatus,
            name="course_generation_status",
            native_enum=False,
            length=16,
        ),
        nullable=False,
        default=GenerationStatus.pending,
    )
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Issue 20: progress for the chapter-tree build. progress_total is set
    # once we know the section count; progress_done increments per section.
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
