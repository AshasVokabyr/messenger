import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String
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
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    participants = relationship("ChatParticipant", back_populates="chat", cascade="all, delete")
    messages = relationship("Message", back_populates="chat", cascade="all, delete")
