import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.chat_participant import ChatParticipant
from app.models.user import User
from app.websocket.auth import get_ws_current_user
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _heartbeat(ws: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            await ws.send_json({"type": "ping"})
    except asyncio.CancelledError:
        pass


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_ws_current_user),
):
    if user is None:
        return

    await manager.connect(user.id, ws)
    heartbeat_task = asyncio.create_task(_heartbeat(ws))

    try:
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")

            if msg_type == "websocket.disconnect":
                break

            if msg_type == "websocket.receive":
                text = msg.get("text")
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "detail": "Invalid JSON"})
                    continue

                action = data.get("action")

                if action == "join":
                    chat_id_str = data.get("chat_id")
                    if not chat_id_str:
                        await ws.send_json({"type": "error", "detail": "Missing chat_id"})
                        continue
                    try:
                        chat_id = uuid.UUID(chat_id_str)
                    except (ValueError, TypeError):
                        await ws.send_json({"type": "error", "detail": "Invalid chat_id"})
                        continue

                    result = await db.execute(
                        select(ChatParticipant).where(
                            ChatParticipant.chat_id == chat_id,
                            ChatParticipant.user_id == user.id,
                        )
                    )
                    if not result.scalar_one_or_none():
                        await ws.send_json({"type": "error", "detail": "Not a member of this chat"})
                        continue

                    manager.subscribe(user.id, chat_id)
                    await ws.send_json({"type": "joined", "chat_id": chat_id_str})

                elif action == "leave":
                    chat_id_str = data.get("chat_id")
                    if not chat_id_str:
                        await ws.send_json({"type": "error", "detail": "Missing chat_id"})
                        continue
                    try:
                        chat_id = uuid.UUID(chat_id_str)
                    except (ValueError, TypeError):
                        await ws.send_json({"type": "error", "detail": "Invalid chat_id"})
                        continue

                    manager.unsubscribe(user.id, chat_id)
                    await ws.send_json({"type": "left", "chat_id": chat_id_str})

                else:
                    await ws.send_json({"type": "error", "detail": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error user_id=%s", user.id)
    finally:
        heartbeat_task.cancel()
        manager.disconnect(user.id, ws)
