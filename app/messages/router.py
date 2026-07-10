import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.messages.schemas import MessageCreateRequest, MessageResponse
from app.models import chat_members
from app.models.chat import Chat
from app.models.message import Message
from app.models.user import User

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/{chat_id}", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    chat_id: uuid.UUID,
    body: MessageCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )

    result = await db.execute(
        select(chat_members).where(
            chat_members.c.chat_id == chat_id,
            chat_members.c.user_id == current_user.id,
        )
    )
    if not result.first():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this chat",
        )

    message = Message(chat_id=chat_id, sender_id=current_user.id, text=body.text)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


@router.get("/{chat_id}", response_model=list[MessageResponse])
async def get_chat_messages(
    chat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/search/", response_model=list[MessageResponse])
async def search_messages(
    q: str = Query(..., min_length=1),
    chat_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(Message).where(Message.text.ilike(f"%{q}%"))
    if chat_id:
        stmt = stmt.where(Message.chat_id == chat_id)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
