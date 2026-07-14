import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    user_id: uuid.UUID
    content: str
    created_at: datetime
    sender_login: str

    model_config = {"from_attributes": True}


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageCursorResponse(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None
