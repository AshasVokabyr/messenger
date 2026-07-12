import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatMemberResponse(BaseModel):
    id: uuid.UUID
    login: str


class ChatResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    type: str
    created_at: datetime
    members: list[ChatMemberResponse]

    model_config = {"from_attributes": True}


class ChatCreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    participant_ids: list[uuid.UUID]
