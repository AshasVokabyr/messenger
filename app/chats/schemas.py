import uuid
from datetime import datetime

from pydantic import BaseModel


class ChatMemberResponse(BaseModel):
    id: uuid.UUID
    username: str

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    type: str
    created_at: datetime
    members: list[ChatMemberResponse]

    model_config = {"from_attributes": True}


class ChatCreateRequest(BaseModel):
    name: str | None = None
    member_ids: list[uuid.UUID]


class ChatAddMemberRequest(BaseModel):
    user_id: uuid.UUID
