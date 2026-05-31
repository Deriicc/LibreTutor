import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import MessageRole


class MessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SendMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
