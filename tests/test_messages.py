import uuid

import pytest
from httpx import AsyncClient

from app.auth.utils import decode_access_token


class TestSendMessage:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    @pytest.mark.asyncio
    async def test_send_message_success(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "hello world"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["content"] == "hello world"
        assert body["chat_id"] == str(chat_id)
        assert "id" in body
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_send_empty_content(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": ""},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_send_too_long_content(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "x" * 4001},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_send_non_member_forbidden(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        token3, _ = await self._register(client, "user_c")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "hello"},
            headers={"Authorization": f"Bearer {token3}"},
        )
        assert resp.status_code == 403


class TestGetMessages:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    async def _setup(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        ids = []
        for i in range(5):
            resp = await client.post(
                f"/chats/{chat_id}/messages",
                json={"content": f"message {i}"},
                headers={"Authorization": f"Bearer {token1}"},
            )
            ids.append(resp.json()["id"])

        return token1, chat_id, ids

    @pytest.mark.asyncio
    async def test_get_messages_empty(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.get(
            f"/chats/{chat_id}/messages",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_get_messages_order(self, client: AsyncClient):
        token1, chat_id, ids = await self._setup(client)

        resp = await client.get(
            f"/chats/{chat_id}/messages",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 5
        assert items[0]["content"] == "message 4"
        assert items[-1]["content"] == "message 0"

    @pytest.mark.asyncio
    async def test_cursor_pagination(self, client: AsyncClient):
        token1, chat_id, ids = await self._setup(client)

        resp = await client.get(
            f"/chats/{chat_id}/messages?limit=3",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        page1 = resp.json()
        assert len(page1["items"]) == 3
        assert page1["next_cursor"] is not None

        resp = await client.get(
            f"/chats/{chat_id}/messages?before={page1['next_cursor']}&limit=3",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        page2 = resp.json()
        assert len(page2["items"]) == 2
        assert page2["next_cursor"] is None

        all_ids = [m["id"] for m in page1["items"]] + [m["id"] for m in page2["items"]]
        assert set(all_ids) == set(ids)

    @pytest.mark.asyncio
    async def test_cursor_no_next_when_less_than_limit(self, client: AsyncClient):
        token1, chat_id, _ = await self._setup(client)

        resp = await client.get(
            f"/chats/{chat_id}/messages?limit=10",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 5
        assert body["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_get_messages_non_member_forbidden(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        token3, _ = await self._register(client, "user_c")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.get(
            f"/chats/{chat_id}/messages",
            headers={"Authorization": f"Bearer {token3}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cursor_invalid_message_id(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]
        fake_id = str(uuid.uuid4())

        resp = await client.get(
            f"/chats/{chat_id}/messages?before={fake_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404
