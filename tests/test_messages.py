import asyncio
import uuid
from unittest.mock import AsyncMock, patch

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

    @pytest.mark.asyncio
    async def test_send_message_publishes_kafka_event(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        with patch("app.chats.router.publish_event", new_callable=AsyncMock) as mock_publish:
            resp = await client.post(
                f"/chats/{chat_id}/messages",
                json={"content": "hello from kafka"},
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert resp.status_code == 201
            body = resp.json()

            mock_publish.assert_awaited_once()
            args, kwargs = mock_publish.call_args
            assert kwargs["topic"] == "message_events"
            assert kwargs["key"] == str(chat_id)
            payload = kwargs["payload"]
            assert payload["id"] == body["id"]
            assert payload["chat_id"] == str(chat_id)
            assert payload["content"] == "hello from kafka"
            assert "sender_login" in payload
            assert "created_at" in payload


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
            await asyncio.sleep(0.01)

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
        returned_ids = {m["id"] for m in items}
        assert returned_ids == set(ids)

    @pytest.mark.asyncio
    async def test_cursor_pagination(self, client: AsyncClient):
        token1, chat_id, ids = await self._setup(client)

        resp = await client.get(
            f"/chats/{chat_id}/messages?limit=3",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        page1 = resp.json()
        assert page1["next_cursor"] is not None

        resp = await client.get(
            f"/chats/{chat_id}/messages?before={page1['next_cursor']}&limit=3",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        page2 = resp.json()

        page1_ids = [m["id"] for m in page1["items"]]
        page2_ids = [m["id"] for m in page2["items"]]
        all_ids = page1_ids + page2_ids
        assert len(all_ids) == 5
        assert len(set(all_ids)) == 5, f"Duplicate IDs: page1={page1_ids}, page2={page2_ids}"
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

    async def _setup(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]
        return token1, chat_id

    @pytest.mark.asyncio
    async def test_search_finds_messages(self, client: AsyncClient):
        token1, chat_id = await self._setup(client)

        await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "hello world"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "goodbye world"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "foo bar"},
            headers={"Authorization": f"Bearer {token1}"},
        )

        resp = await client.get(
            f"/chats/{chat_id}/messages/search?q=world",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2
        assert all("world" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, client: AsyncClient):
        token1, chat_id = await self._setup(client)

        await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "HELLO World"},
            headers={"Authorization": f"Bearer {token1}"},
        )

        resp = await client.get(
            f"/chats/{chat_id}/messages/search?q=hello",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_non_member_forbidden(self, client: AsyncClient):
        token1, chat_id = await self._setup(client)
        token3, _ = await self._register(client, "user_c")

        resp = await client.get(
            f"/chats/{chat_id}/messages/search?q=hello",
            headers={"Authorization": f"Bearer {token3}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_search_special_chars(self, client: AsyncClient):
        token1, chat_id = await self._setup(client)

        await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "100% done"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        await client.post(
            f"/chats/{chat_id}/messages",
            json={"content": "test_message"},
            headers={"Authorization": f"Bearer {token1}"},
        )

        resp = await client.get(
            f"/chats/{chat_id}/messages/search?q=100%25",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert "100% done" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_search_limit(self, client: AsyncClient):
        token1, chat_id = await self._setup(client)

        for i in range(5):
            await client.post(
                f"/chats/{chat_id}/messages",
                json={"content": f"message {i}"},
                headers={"Authorization": f"Bearer {token1}"},
            )

        resp = await client.get(
            f"/chats/{chat_id}/messages/search?q=message&limit=3",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    @pytest.mark.asyncio
    async def test_search_empty_query(self, client: AsyncClient):
        token1, chat_id = await self._setup(client)

        resp = await client.get(
            f"/chats/{chat_id}/messages/search?q=",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 422
