import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.messages.schemas import MessageCreateRequest, MessageResponse
from app.models.chat_participant import ChatParticipant
from app.models.message import Message
from app.models.user import User

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/search/", response_model=list[MessageResponse])
async def search_messages(
    q: str = Query(..., min_length=1),
    chat_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if chat_id:
        result = await db.execute(
            select(ChatParticipant).where(
                ChatParticipant.chat_id == chat_id,
                ChatParticipant.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this chat",
            )

    stmt = select(Message).where(Message.content.ilike(f"%{safe_q}%", escape="\\"))
    if chat_id:
        stmt = stmt.where(Message.chat_id == chat_id)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
