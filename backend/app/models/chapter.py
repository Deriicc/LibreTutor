import enum
import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class KPStatus(str, enum.Enum):
    untouched = "untouched"
    in_progress = "in_progress"
    passed = "passed"


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sections: Mapped[list["Section"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="Section.order_index",
    )


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    chapter: Mapped[Chapter] = relationship(back_populates="sections")
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="KnowledgePoint.order_index",
    )


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[KPStatus] = mapped_column(
        SAEnum(KPStatus, name="kp_status", native_enum=False, length=32),
        nullable=False,
        default=KPStatus.untouched,
    )
    boundary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Bumped on retry; identifies the "live" KPExerciseSet row at
    # (kp_id, current_attempt). Past attempts are kept for the report.
    current_attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    section: Mapped[Section] = relationship(back_populates="knowledge_points")
