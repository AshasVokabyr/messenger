import logging
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, list[WebSocket]] = {}
        self._chat_subscriptions: dict[uuid.UUID, set[uuid.UUID]] = {}

    async def connect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)
        logger.info("WebSocket connected user_id=%s", user_id)

    def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        if user_id in self._connections and ws in self._connections[user_id]:
            self._connections[user_id].remove(ws)
            if not self._connections[user_id]:
                del self._connections[user_id]
        self._unsubscribe_all(user_id)
        logger.info("WebSocket disconnected user_id=%s", user_id)

    def subscribe(self, user_id: uuid.UUID, chat_id: uuid.UUID) -> None:
        self._chat_subscriptions.setdefault(chat_id, set()).add(user_id)
        logger.info("User %s subscribed to chat %s", user_id, chat_id)

    def unsubscribe(self, user_id: uuid.UUID, chat_id: uuid.UUID) -> None:
        self._chat_subscriptions.get(chat_id, set()).discard(user_id)
        if chat_id in self._chat_subscriptions and not self._chat_subscriptions[chat_id]:
            del self._chat_subscriptions[chat_id]
        logger.info("User %s unsubscribed from chat %s", user_id, chat_id)

    def _unsubscribe_all(self, user_id: uuid.UUID) -> None:
        for chat_id in list(self._chat_subscriptions):
            self._chat_subscriptions[chat_id].discard(user_id)
            if not self._chat_subscriptions[chat_id]:
                del self._chat_subscriptions[chat_id]

    def get_chat_subscribers(self, chat_id: uuid.UUID) -> set[uuid.UUID]:
        return self._chat_subscriptions.get(chat_id, set()).copy()

    async def send_to_user(self, user_id: uuid.UUID, message: dict) -> None:
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("Failed to send to user_id=%s", user_id)

    async def broadcast_to_chat(self, chat_id: uuid.UUID, message: dict) -> None:
        for uid in self.get_chat_subscribers(chat_id):
            await self.send_to_user(uid, message)


manager = ConnectionManager()
