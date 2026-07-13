import uuid

import logging

from app.websocket.manager import manager

logger = logging.getLogger(__name__)


async def handle_message_event(payload: dict) -> None:
    chat_id = uuid.UUID(payload["chat_id"])
    user_id = uuid.UUID(payload["user_id"])
    await manager.broadcast_to_chat(chat_id, {"type": "new_message", "data": payload})
    logger.info(
        "Broadcast message event: chat_id=%s user_id=%s",
        chat_id, user_id,
    )


async def handle_chat_event(payload: dict) -> None:
    chat_id = uuid.UUID(payload["chat_id"])
    event_type = payload["type"]
    await manager.broadcast_to_chat(chat_id, {"type": event_type, "data": payload})
    logger.info(
        "Broadcast chat event: type=%s chat_id=%s", event_type, chat_id,
    )
