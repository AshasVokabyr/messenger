import uuid

import pytest
from httpx import AsyncClient

from app.auth.utils import decode_access_token


class TestCreatePersonalChat:
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
    async def test_create_personal_success(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        resp = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["type"] == "personal"
        assert body["name"] is None
        assert len(body["members"]) == 2

    @pytest.mark.asyncio
    async def test_return_existing_personal_chat(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        resp1 = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp1.status_code == 201
        chat_id = resp1.json()["id"]

        resp2 = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["id"] == chat_id

    @pytest.mark.asyncio
    async def test_create_personal_with_self(self, client: AsyncClient):
        token, user_id = await self._register(client, "user_a")

        resp = await client.post(
            f"/chats/personal/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "yourself" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_personal_nonexistent_user(self, client: AsyncClient):
        token, _ = await self._register(client, "user_a")
        fake_id = str(uuid.uuid4())

        resp = await client.post(
            f"/chats/personal/{fake_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


class TestCreateGroupChat:
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
    async def test_create_group_success(self, client: AsyncClient):
        token1, user1_id = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        resp = await client.post(
            "/chats/group",
            json={
                "name": "Test Group",
                "participant_ids": [str(user_b_id), str(user_c_id)],
            },
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["type"] == "group"
        assert body["name"] == "Test Group"
        assert len(body["members"]) == 3

        member_ids = {m["id"] for m in body["members"]}
        assert str(user1_id) in member_ids
        assert str(user_b_id) in member_ids
        assert str(user_c_id) in member_ids

    @pytest.mark.asyncio
    async def test_create_group_without_name(self, client: AsyncClient):
        token, _ = await self._register(client, "user_a")

        resp = await client.post(
            "/chats/group",
            json={"participant_ids": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_group_empty_participants(self, client: AsyncClient):
        token, _ = await self._register(client, "user_a")

        resp = await client.post(
            "/chats/group",
            json={"name": "Group", "participant_ids": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_group_nonexistent_participant(self, client: AsyncClient):
        token, _ = await self._register(client, "user_a")
        fake_id = str(uuid.uuid4())

        resp = await client.post(
            "/chats/group",
            json={"name": "Group", "participant_ids": [fake_id]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
