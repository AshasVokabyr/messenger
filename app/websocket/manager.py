import logging
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, list[WebSocket]] = {}

    async def connect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)
        logger.info("WebSocket connected user_id=%s", user_id)

    def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        self._connections.setdefault(user_id, []).remove(ws)
        if not self._connections[user_id]:
            del self._connections[user_id]
        logger.info("WebSocket disconnected user_id=%s", user_id)

    async def send_to_user(self, user_id: uuid.UUID, message: dict) -> None:
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("Failed to send to user_id=%s", user_id)

    async def broadcast_to_chat(self, chat_id: uuid.UUID, message: dict) -> None:
        from sqlalchemy import select

        from app.db import async_session
        from app.models.chat_participant import ChatParticipant

        async with async_session() as session:
            result = await session.execute(
                select(ChatParticipant.user_id).where(
                    ChatParticipant.chat_id == chat_id
                )
            )
            user_ids = result.scalars().all()

        for uid in user_ids:
            await self.send_to_user(uid, message)


manager = ConnectionManager()
