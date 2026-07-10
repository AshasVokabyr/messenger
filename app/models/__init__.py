from app.models.user import User  # noqa: F401
from app.models.chat import Chat, ChatType  # noqa: F401
from app.models.message import Message  # noqa: F401

from sqlalchemy import Table, Column, ForeignKey
from app.db import Base

chat_members = Table(
    "chat_members",
    Base.metadata,
    Column("chat_id", ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)
