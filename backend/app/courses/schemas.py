import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import GenerationStatus, KPStatus


class CourseOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    generation_status: GenerationStatus
    generation_error: str | None = None
    progress_done: int = 0
    progress_total: int = 0
    kp_passed: int = 0
    kp_total: int = 0

    model_config = {"from_attributes": True}


class KnowledgePointOut(BaseModel):
    id: uuid.UUID
    title: str
    status: KPStatus
    boundary: dict[str, Any]
    order_index: int

    model_config = {"from_attributes": True}


class SectionOut(BaseModel):
    id: uuid.UUID
    title: str
    order_index: int
    status: KPStatus
    knowledge_points: list[KnowledgePointOut]

    model_config = {"from_attributes": True}


class ChapterOut(BaseModel):
    id: uuid.UUID
    title: str
    order_index: int
    status: KPStatus
    sections: list[SectionOut]

    model_config = {"from_attributes": True}


class ChapterTreeOut(BaseModel):
    course_id: uuid.UUID
    generation_status: GenerationStatus
    generation_error: str | None = None
    chapters: list[ChapterOut]


class TeacherConfigOut(BaseModel):
    scene: str
    learner_context: str
    has_generated_few_shots: bool
    scene_dirty: bool
    has_avatar: bool = False


class TeacherConfigIn(BaseModel):
    scene: str = ""
    learner_context: str = ""
