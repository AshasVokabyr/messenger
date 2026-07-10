import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

import enum


class ChatType(str, enum.Enum):
    personal = "personal"
    group = "group"


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[ChatType] = mapped_column(
        Enum(ChatType, name="chat_type"), nullable=False, default=ChatType.personal
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    members = relationship("User", secondary="chat_members", back_populates="chats")
    messages = relationship("Message", back_populates="chat")
