import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.utils import decode_access_token
from app.db import Base
from app.main import app
from app.websocket.manager import ConnectionManager
from tests.conftest import test_engine


@pytest.fixture(scope="session")
def _setup_db():
    async def init():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    yield


@pytest.fixture(scope="session")
def _engine():
    async def init():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    yield
    async def cleanup():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    asyncio.run(cleanup())


@pytest.fixture
def _reset_db():
    async def reset():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(reset())
    yield


@pytest.fixture(scope="session")
def tc_session(_engine):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_kafka():
    with patch("app.chats.router.publish_event", new_callable=AsyncMock):
        yield


@pytest.mark.usefixtures("_reset_db")
class TestWebSocketAuth:
    def test_no_token(self):
        with TestClient(app) as tc:
            with pytest.raises(WebSocketDisconnect) as exc:
                with tc.websocket_connect("/ws"):
                    pass
            assert exc.value.code == 1008

    def test_invalid_token(self):
        with TestClient(app) as tc:
            with pytest.raises(WebSocketDisconnect) as exc:
                with tc.websocket_connect("/ws?token=invalid_jwt"):
                    pass
            assert exc.value.code == 1008

    def test_valid_token(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "ws_auth", "password": "secret123"})
        assert resp.status_code == 201
        token = resp.json()["access_token"]

        with tc_session.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"action": "leave"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "missing chat_id" in data["detail"].lower()


class TestConnectionManager:
    def test_connect_disconnect(self):
        cm = ConnectionManager()
        user_id = uuid.uuid4()
        mock_ws = AsyncMock()

        async def run():
            await cm.connect(user_id, mock_ws)
            assert user_id in cm._connections
            assert mock_ws in cm._connections[user_id]

            cm.disconnect(user_id, mock_ws)
            assert user_id not in cm._connections

        asyncio.run(run())

    def test_disconnect_safe_when_not_found(self):
        cm = ConnectionManager()
        user_id = uuid.uuid4()
        mock_ws = object()
        cm.disconnect(user_id, mock_ws)

    def test_subscribe_unsubscribe(self):
        cm = ConnectionManager()
        user_id = uuid.uuid4()
        chat_id = uuid.uuid4()

        cm.subscribe(user_id, chat_id)
        assert cm.get_chat_subscribers(chat_id) == {user_id}

        cm.unsubscribe(user_id, chat_id)
        assert cm.get_chat_subscribers(chat_id) == set()

    def test_subscribe_unknown_chat(self):
        cm = ConnectionManager()
        assert cm.get_chat_subscribers(uuid.uuid4()) == set()

    def test_disconnect_cleans_subscriptions(self):
        cm = ConnectionManager()
        user_id = uuid.uuid4()
        chat_id = uuid.uuid4()

        cm.subscribe(user_id, chat_id)
        cm.disconnect(user_id, object())
        assert cm.get_chat_subscribers(chat_id) == set()

    def test_multiple_users_same_chat(self):
        cm = ConnectionManager()
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        chat_id = uuid.uuid4()

        cm.subscribe(user_a, chat_id)
        cm.subscribe(user_b, chat_id)
        assert cm.get_chat_subscribers(chat_id) == {user_a, user_b}

        cm.unsubscribe(user_a, chat_id)
        assert cm.get_chat_subscribers(chat_id) == {user_b}


@pytest.mark.usefixtures("_reset_db")
class TestWebSocketJoin:
    def _create_chat(self, tc_session, token, other_user_id):
        resp = tc_session.post(
            f"/chats/personal/{other_user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_join_as_member(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "jm_a", "password": "secret123"})
        token_a = resp.json()["access_token"]

        resp = tc_session.post("/auth/register", json={"login": "jm_b", "password": "secret123"})
        user_b_id = uuid.UUID(decode_access_token(resp.json()["access_token"])["sub"])

        chat_id = self._create_chat(tc_session, token_a, user_b_id)

        with tc_session.websocket_connect(f"/ws?token={token_a}") as ws:
            ws.send_json({"action": "join", "chat_id": chat_id})
            data = ws.receive_json()
            assert data["type"] == "joined"
            assert data["chat_id"] == chat_id

    def test_join_as_non_member(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "jnm_a", "password": "secret123"})
        token_a = resp.json()["access_token"]

        resp = tc_session.post("/auth/register", json={"login": "jnm_b", "password": "secret123"})
        user_b_id = uuid.UUID(decode_access_token(resp.json()["access_token"])["sub"])

        chat_id = self._create_chat(tc_session, token_a, user_b_id)

        resp = tc_session.post("/auth/register", json={"login": "jnm_c", "password": "secret123"})
        token_c = resp.json()["access_token"]

        with tc_session.websocket_connect(f"/ws?token={token_c}") as ws:
            ws.send_json({"action": "join", "chat_id": chat_id})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "not a member" in data["detail"].lower()

    def test_join_missing_chat_id(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "jmiss", "password": "secret123"})
        token = resp.json()["access_token"]

        with tc_session.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"action": "join"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "missing chat_id" in data["detail"].lower()

    def test_join_invalid_chat_id(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "jinv", "password": "secret123"})
        token = resp.json()["access_token"]

        with tc_session.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"action": "join", "chat_id": "not-a-uuid"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "invalid chat_id" in data["detail"].lower()


@pytest.mark.usefixtures("_reset_db")
class TestWebSocketLeave:
    def test_leave(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "lv_a", "password": "secret123"})
        token = resp.json()["access_token"]

        resp = tc_session.post("/auth/register", json={"login": "lv_b", "password": "secret123"})
        other_id = uuid.UUID(decode_access_token(resp.json()["access_token"])["sub"])

        resp = tc_session.post(
            f"/chats/personal/{other_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        chat_id = resp.json()["id"]

        with tc_session.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"action": "join", "chat_id": chat_id})
            ws.receive_json()

            ws.send_json({"action": "leave", "chat_id": chat_id})
            data = ws.receive_json()
            assert data["type"] == "left"
            assert data["chat_id"] == chat_id


@pytest.mark.usefixtures("_reset_db")
class TestWebSocketErrors:
    def test_invalid_json(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "wserr", "password": "secret123"})
        token = resp.json()["access_token"]

        with tc_session.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_text("not valid json")
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "invalid json" in data["detail"].lower()

    def test_unknown_action(self, tc_session, mock_kafka):
        resp = tc_session.post("/auth/register", json={"login": "wsunk", "password": "secret123"})
        token = resp.json()["access_token"]

        with tc_session.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"action": "fly"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "unknown action" in data["detail"].lower()
