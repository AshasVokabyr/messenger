import uuid

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: uuid.UUID
    login: str
