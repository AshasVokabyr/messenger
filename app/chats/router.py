import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

logger = logging.getLogger(__name__)
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.chats.schemas import (
    AddParticipantsRequest,
    ChatCreateGroupRequest,
    ChatMemberResponse,
    ChatResponse,
    RoleChangeRequest,
)
from app.db import get_db
from app.kafka.producer import publish_event
from app.messages.schemas import MessageCreateRequest, MessageCursorResponse, MessageResponse
from app.models.chat import Chat, ChatType
from app.models.chat_participant import ChatParticipant, ParticipantRole
from app.models.message import Message
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
            ChatMemberResponse(id=p.user.id, login=p.user.login, role=p.role.value)
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

    await publish_event(
        topic="chat_events",
        key=str(chat.id),
        payload={
            "type": "chat_created",
            "chat_id": str(chat.id),
            "chat_type": chat.type.value,
            "user_ids": [str(current_user.id), str(user_id)],
        },
    )

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

    await publish_event(
        topic="chat_events",
        key=str(chat.id),
        payload={
            "type": "chat_created",
            "chat_id": str(chat.id),
            "chat_type": chat.type.value,
            "name": chat.name,
            "user_ids": [str(uid) for uid in all_ids],
        },
    )

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
                ChatMemberResponse(id=p.user.id, login=p.user.login, role=p.role.value)
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
            ChatMemberResponse(id=p.user.id, login=p.user.login, role=p.role.value)
            for p in chat.participants
        ],
    )


async def _require_admin(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Chat:
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
    if chat.type != ChatType.group:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Participants can only be managed in group chats",
        )
    me = next(
        (p for p in chat.participants if p.user_id == user_id), None
    )
    if me is None or me.role != ParticipantRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only chat admins can manage participants",
        )
    return chat


@router.post("/{chat_id}/participants", response_model=ChatResponse)
async def add_participants(
    chat_id: uuid.UUID,
    body: AddParticipantsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chat = await _require_admin(chat_id, current_user.id, db)

    for uid in body.user_ids:
        result = await db.execute(select(User).where(User.id == uid))
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {uid} not found",
            )

    existing_ids = {p.user_id for p in chat.participants}
    for uid in body.user_ids:
        if uid in existing_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User {uid} is already a participant",
            )

    for uid in body.user_ids:
        db.add(ChatParticipant(chat_id=chat.id, user_id=uid, role=ParticipantRole.member))

    await db.commit()
    db.expire(chat)

    await publish_event(
        topic="chat_events",
        key=str(chat_id),
        payload={
            "type": "participants_added",
            "chat_id": str(chat_id),
            "user_ids": [str(uid) for uid in body.user_ids],
        },
    )

    return await _build_chat_response(chat_id, db)


@router.delete("/{chat_id}/participants/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chat = await _require_admin(chat_id, current_user.id, db)

    target = next(
        (p for p in chat.participants if p.user_id == user_id), None
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a participant of this chat",
        )

    if target.role == ParticipantRole.admin:
        admin_count = sum(
            1 for p in chat.participants if p.role == ParticipantRole.admin
        )
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin",
            )

    await db.delete(target)
    await db.commit()

    await publish_event(
        topic="chat_events",
        key=str(chat_id),
        payload={
            "type": "participant_removed",
            "chat_id": str(chat_id),
            "user_id": str(user_id),
        },
    )

    return None


@router.patch("/{chat_id}/participants/{user_id}/role", response_model=ChatResponse)
async def change_participant_role(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        chat = await _require_admin(chat_id, current_user.id, db)

        target = next(
            (p for p in chat.participants if p.user_id == user_id), None
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User is not a participant of this chat",
            )

        if target.role == ParticipantRole.admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change role of an admin",
            )

        target.role = ParticipantRole(body.role)
        await db.commit()

        try:
            await publish_event(
                topic="chat_events",
                key=str(chat_id),
                payload={
                    "type": "participant_role_changed",
                    "chat_id": str(chat_id),
                    "user_id": str(user_id),
                    "role": body.role,
                },
            )
        except Exception:
            logger.exception("Failed to publish role change event")

        return await _build_chat_response(chat_id, db)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error in change_participant_role")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_chat_message(
    chat_id: uuid.UUID,
    body: MessageCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    message = Message(chat_id=chat_id, user_id=current_user.id, content=body.content)
    db.add(message)
    await db.commit()
    await db.refresh(message)

    await publish_event(
        topic="message_events",
        key=str(chat_id),
        payload={
            "id": str(message.id),
            "chat_id": str(chat_id),
            "user_id": str(current_user.id),
            "content": body.content,
            "created_at": message.created_at.isoformat(),
            "sender_login": current_user.login,
        },
    )

    return MessageResponse(
        id=message.id,
        chat_id=message.chat_id,
        user_id=message.user_id,
        content=message.content,
        created_at=message.created_at,
        sender_login=current_user.login,
    )


@router.get("/{chat_id}/messages/search", response_model=list[MessageResponse])
async def search_chat_messages(
    chat_id: uuid.UUID,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
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

    safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stmt = (
        select(Message)
        .options(selectinload(Message.user))
        .where(
            Message.chat_id == chat_id,
            Message.content.ilike(f"%{safe_q}%", escape="\\"),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        MessageResponse(
            id=m.id, chat_id=m.chat_id, user_id=m.user_id,
            content=m.content, created_at=m.created_at,
            sender_login=m.user.login,
        )
        for m in messages
    ]


@router.get("/{chat_id}/messages", response_model=MessageCursorResponse)
async def get_chat_messages_cursor(
    chat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    before: uuid.UUID | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
):
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

    base_order = Message.created_at.desc()
    stmt = select(Message).options(selectinload(Message.user)).where(Message.chat_id == chat_id)

    if before is not None:
        cursor_result = await db.execute(
            select(Message.created_at, Message.id).where(Message.id == before)
        )
        row = cursor_result.one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cursor message not found",
            )
        cursor_created_at, cursor_id = row
        stmt = stmt.where(
            (Message.created_at < cursor_created_at)
            | ((Message.created_at == cursor_created_at) & (Message.id < cursor_id))
        )

    stmt = stmt.order_by(base_order, Message.id.desc()).limit(limit)

    messages = (await db.execute(stmt)).scalars().all()
    items = [
        MessageResponse(
            id=m.id, chat_id=m.chat_id, user_id=m.user_id,
            content=m.content, created_at=m.created_at,
            sender_login=m.user.login,
        )
        for m in messages
    ]
    next_cursor = str(messages[-1].id) if len(messages) == limit else None
    return MessageCursorResponse(items=items, next_cursor=next_cursor)
