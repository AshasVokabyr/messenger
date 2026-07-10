import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.chats.schemas import ChatCreateRequest, ChatMemberResponse, ChatResponse
from app.db import get_db
from app.models.chat import Chat, ChatType
from app.models.chat_participant import ChatParticipant, ParticipantRole
from app.models.user import User

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("/", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: ChatCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(body.member_ids) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 1 other member required",
        )

    for mid in body.member_ids:
        result = await db.execute(select(User).where(User.id == mid))
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {mid} not found",
            )

    chat_type = ChatType.group if body.name else ChatType.personal

    chat = Chat(name=body.name, type=chat_type, created_by=current_user.id)
    db.add(chat)
    await db.flush()

    all_member_ids = set(body.member_ids) | {current_user.id}
    for mid in all_member_ids:
        role = ParticipantRole.admin if mid == current_user.id else ParticipantRole.member
        participant = ChatParticipant(chat_id=chat.id, user_id=mid, role=role)
        db.add(participant)

    await db.commit()

    result = await db.execute(
        select(Chat)
        .where(Chat.id == chat.id)
        .options(selectinload(Chat.participants).selectinload(ChatParticipant.user))
    )
    chat = result.scalar_one()
    return ChatResponse(
        id=chat.id,
        name=chat.name,
        type=chat.type.value,
        created_at=chat.created_at,
        members=[
            ChatMemberResponse(id=p.user.id, login=p.user.login)
            for p in chat.participants
        ],
    )


@router.get("/", response_model=list[ChatResponse])
async def list_chats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Chat)
        .where(
            Chat.id.in_(
                select(ChatParticipant.chat_id).where(
                    ChatParticipant.user_id == current_user.id
                )
            )
        )
        .options(selectinload(Chat.participants).selectinload(ChatParticipant.user))
    )
    chats = result.scalars().all()
    return [
        ChatResponse(
            id=chat.id,
            name=chat.name,
            type=chat.type.value,
            created_at=chat.created_at,
            members=[
                ChatMemberResponse(id=p.user.id, login=p.user.login)
                for p in chat.participants
            ],
        )
        for chat in chats
    ]


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Chat)
        .where(Chat.id == chat_id)
        .options(selectinload(Chat.participants).selectinload(ChatParticipant.user))
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    return ChatResponse(
        id=chat.id,
        name=chat.name,
        type=chat.type.value,
        created_at=chat.created_at,
        members=[
            ChatMemberResponse(id=p.user.id, login=p.user.login)
            for p in chat.participants
        ],
    )
