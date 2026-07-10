import uuid
from datetime import datetime

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    sender_id: uuid.UUID
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreateRequest(BaseModel):
    text: str
