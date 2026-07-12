import uuid

import pytest
from httpx import AsyncClient

from app.auth.utils import decode_access_token


class TestSearchMessages:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    async def _send_message(self, client, token, chat_id, content):
        return await client.post(
            f"/messages/{chat_id}",
            json={"content": content},
            headers={"Authorization": f"Bearer {token}"},
        )

    @pytest.mark.asyncio
    async def test_search_finds_messages(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        await self._send_message(client, token1, chat_id, "hello world")
        await self._send_message(client, token1, chat_id, "goodbye world")
        await self._send_message(client, token1, chat_id, "foo bar")

        resp = await client.get(
            f"/messages/{chat_id}/messages/search?q=world",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2
        assert all("world" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        await self._send_message(client, token1, chat_id, "HELLO World")

        resp = await client.get(
            f"/messages/{chat_id}/messages/search?q=hello",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_non_member_forbidden(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        token3, _ = await self._register(client, "user_c")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.get(
            f"/messages/{chat_id}/messages/search?q=hello",
            headers={"Authorization": f"Bearer {token3}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_search_special_chars(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        await self._send_message(client, token1, chat_id, "100% done")
        await self._send_message(client, token1, chat_id, "test_message")

        resp = await client.get(
            f"/messages/{chat_id}/messages/search?q=100%25",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_limit(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        for i in range(5):
            await self._send_message(client, token1, chat_id, f"message {i}")

        resp = await client.get(
            f"/messages/{chat_id}/messages/search?q=message&limit=3",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3
