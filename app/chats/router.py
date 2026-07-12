import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.chats.schemas import ChatCreateGroupRequest, ChatMemberResponse, ChatResponse
from app.db import get_db
from app.models.chat import Chat, ChatType
from app.models.chat_participant import ChatParticipant, ParticipantRole
from app.models.user import User

router = APIRouter(prefix="/chats", tags=["chats"])


async def _build_chat_response(chat_id: uuid.UUID, db: AsyncSession) -> ChatResponse:
    result = await db.execute(
        select(Chat)
        .where(Chat.id == chat_id)
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


@router.post("/personal/{user_id}", response_model=ChatResponse)
async def create_personal_chat(
    user_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create personal chat with yourself",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    existing = await db.execute(
        select(Chat).where(
            Chat.type == ChatType.personal,
            exists(
                select(1).where(
                    ChatParticipant.chat_id == Chat.id,
                    ChatParticipant.user_id == current_user.id,
                )
            ),
            exists(
                select(1).where(
                    ChatParticipant.chat_id == Chat.id,
                    ChatParticipant.user_id == user_id,
                )
            ),
        )
    )
    existing_chat = existing.scalar_one_or_none()
    if existing_chat is not None:
        response.status_code = status.HTTP_200_OK
        return await _build_chat_response(existing_chat.id, db)

    response.status_code = status.HTTP_201_CREATED
    chat = Chat(type=ChatType.personal, created_by=current_user.id)
    db.add(chat)
    await db.flush()

    for mid in (current_user.id, user_id):
        db.add(ChatParticipant(chat_id=chat.id, user_id=mid, role=ParticipantRole.member))

    await db.commit()
    return await _build_chat_response(chat.id, db)


@router.post("/group", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_group_chat(
    body: ChatCreateGroupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(body.participant_ids) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 1 other participant required",
        )

    for pid in body.participant_ids:
        result = await db.execute(select(User).where(User.id == pid))
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {pid} not found",
            )

    chat = Chat(name=body.name, type=ChatType.group, created_by=current_user.id)
    db.add(chat)
    await db.flush()

    all_ids = set(body.participant_ids) | {current_user.id}
    for mid in all_ids:
        role = ParticipantRole.admin if mid == current_user.id else ParticipantRole.member
        db.add(ChatParticipant(chat_id=chat.id, user_id=mid, role=role))

    await db.commit()
    return await _build_chat_response(chat.id, db)


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
