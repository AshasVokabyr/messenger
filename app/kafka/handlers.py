import uuid

import logging

from app.websocket.manager import manager

logger = logging.getLogger(__name__)


async def handle_message_event(payload: dict) -> None:
    try:
        chat_id = uuid.UUID(payload["chat_id"])
        event_type = payload.get("type", "message")
        await manager.broadcast_to_chat(chat_id, {"type": event_type, "data": payload})
        logger.info(
            "Broadcast message event: type=%s chat_id=%s", event_type, chat_id,
        )
    except Exception:
        logger.exception("Failed to handle message event: %s", payload)


async def handle_chat_event(payload: dict) -> None:
    try:
        chat_id = uuid.UUID(payload["chat_id"])
        event_type = payload["type"]
        await manager.broadcast_to_chat(chat_id, {"type": event_type, "data": payload})
        logger.info(
            "Broadcast chat event: type=%s chat_id=%s", event_type, chat_id,
        )
    except Exception:
        logger.exception("Failed to handle chat event: %s", payload)
