import uuid
from unittest.mock import AsyncMock, patch

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


class TestParticipants:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    async def _create_group(self, client, token, participant_ids, name="Group"):
        resp = await client.post(
            "/chats/group",
            json={"name": name, "participant_ids": participant_ids},
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp

    @pytest.mark.asyncio
    async def test_admin_adds_member(self, client: AsyncClient):
        token1, user1_id = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/participants",
            json={"user_ids": [str(user_c_id)]},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        member_ids = {m["id"] for m in body["members"]}
        assert str(user_c_id) in member_ids
        assert len(body["members"]) == 3

    @pytest.mark.asyncio
    async def test_non_admin_cannot_add(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        token2, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/participants",
            json={"user_ids": [str(user_c_id)]},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_add_to_personal_chat_fails(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        chat = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/participants",
            json={"user_ids": [str(user_c_id)]},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_add_nonexistent_user(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]
        fake_id = str(uuid.uuid4())

        resp = await client.post(
            f"/chats/{chat_id}/participants",
            json={"user_ids": [fake_id]},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_duplicate_participant(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/participants",
            json={"user_ids": [str(user_b_id)]},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_admin_removes_member(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.delete(
            f"/chats/{chat_id}/participants/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_cannot_remove_last_admin(self, client: AsyncClient):
        token1, user1_id = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.delete(
            f"/chats/{chat_id}/participants/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 204

        resp = await client.delete(
            f"/chats/{chat_id}/participants/{user1_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 400
        assert "last admin" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_non_admin_cannot_remove(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        token2, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.delete(
            f"/chats/{chat_id}/participants/{user_c_id}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_remove_nonexistent_participant(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]
        fake_id = str(uuid.uuid4())

        resp = await client.delete(
            f"/chats/{chat_id}/participants/{fake_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_add_participant_publishes_kafka_event(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        with patch("app.chats.router.publish_event", new_callable=AsyncMock) as mock_publish:
            resp = await client.post(
                f"/chats/{chat_id}/participants",
                json={"user_ids": [str(user_c_id)]},
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert resp.status_code == 200

            mock_publish.assert_awaited_once()
            args, kwargs = mock_publish.call_args
            assert kwargs["topic"] == "chat_events"
            assert kwargs["key"] == str(chat_id)
            assert kwargs["payload"]["type"] == "participants_added"
            assert str(user_c_id) in kwargs["payload"]["user_ids"]

    @pytest.mark.asyncio
    async def test_remove_participant_publishes_kafka_event(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        with patch("app.chats.router.publish_event", new_callable=AsyncMock) as mock_publish:
            resp = await client.delete(
                f"/chats/{chat_id}/participants/{user_b_id}",
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert resp.status_code == 204

            mock_publish.assert_awaited_once()
            args, kwargs = mock_publish.call_args
            assert kwargs["topic"] == "chat_events"
            assert kwargs["key"] == str(chat_id)
            assert kwargs["payload"]["type"] == "participant_removed"
            assert kwargs["payload"]["user_id"] == str(user_b_id)


class TestLeaveChat:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    async def _create_group(self, client: AsyncClient, token: str, participant_ids: list[str]):
        resp = await client.post(
            "/chats/group",
            json={"name": "Test Group", "participant_ids": participant_ids},
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp

    @pytest.mark.asyncio
    async def test_leave_group_success(self, client: AsyncClient):
        token1, user1_id = await self._register(client, "user_a")
        token2, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/leave",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Left the chat"

        resp = await client.get(
            f"/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 200
        member_ids = [m["id"] for m in resp.json()["members"]]
        assert str(user1_id) not in member_ids

    @pytest.mark.asyncio
    async def test_leave_last_participant_deletes_group_chat(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        token2, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/leave",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Left the chat"

        resp = await client.post(
            f"/chats/{chat_id}/leave",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        assert "deleted" in resp.json()["detail"]

        resp = await client.get(
            f"/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_leave_personal_deletes_chat(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        resp = await client.post(
            f"/chats/personal/{user_b_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        chat_id = resp.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/leave",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        assert "deleted" in resp.json()["detail"]

        resp = await client.get(
            f"/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_leave_non_member_404(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")
        token3, _ = await self._register(client, "user_c")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.post(
            f"/chats/{chat_id}/leave",
            headers={"Authorization": f"Bearer {token3}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_leave_unauthorized(self, client: AsyncClient):
        resp = await client.post(f"/chats/{uuid.uuid4()}/leave")
        assert resp.status_code == 401


class TestDeleteChat:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    async def _create_group(self, client: AsyncClient, token: str, participant_ids: list[str]):
        resp = await client.post(
            "/chats/group",
            json={"name": "Test Group", "participant_ids": participant_ids},
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp

    @pytest.mark.asyncio
    async def test_delete_chat_as_admin(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.delete(
            f"/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 204

        resp = await client.get(
            f"/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_chat_as_member_403(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        token2, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.delete(
            f"/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_chat_not_found(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")

        resp = await client.delete(
            f"/chats/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_chat_unauthorized(self, client: AsyncClient):
        resp = await client.delete(f"/chats/{uuid.uuid4()}")
        assert resp.status_code == 401


class TestChangeRole:
    async def _register(self, client: AsyncClient, login: str):
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        data = resp.json()
        from app.auth.utils import decode_access_token
        payload = decode_access_token(data["access_token"])
        user_id = uuid.UUID(payload["sub"])
        return data["access_token"], user_id

    async def _create_group(self, client, token, participant_ids, name="Group"):
        resp = await client.post(
            "/chats/group",
            json={"name": name, "participant_ids": participant_ids},
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp

    @pytest.mark.asyncio
    async def test_admin_promotes_member_to_moderator(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.patch(
            f"/chats/{chat_id}/participants/{user_b_id}/role",
            json={"role": "moderator"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        members = resp.json()["members"]
        target = next(m for m in members if m["id"] == str(user_b_id))
        assert target["role"] == "moderator"

    @pytest.mark.asyncio
    async def test_admin_demotes_moderator_to_member(self, client: AsyncClient):
        token1, user1_id = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        await client.patch(
            f"/chats/{chat_id}/participants/{user_b_id}/role",
            json={"role": "moderator"},
            headers={"Authorization": f"Bearer {token1}"},
        )

        resp = await client.patch(
            f"/chats/{chat_id}/participants/{user_b_id}/role",
            json={"role": "member"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 200
        members = resp.json()["members"]
        target = next(m for m in members if m["id"] == str(user_b_id))
        assert target["role"] == "member"

    @pytest.mark.asyncio
    async def test_non_admin_cannot_change_role(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        token2, user_b_id = await self._register(client, "user_b")
        _, user_c_id = await self._register(client, "user_c")

        chat = await self._create_group(client, token1, [str(user_b_id), str(user_c_id)])
        chat_id = chat.json()["id"]

        resp = await client.patch(
            f"/chats/{chat_id}/participants/{user_c_id}/role",
            json={"role": "moderator"},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_change_role_nonexistent_participant(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]
        fake_id = str(uuid.uuid4())

        resp = await client.patch(
            f"/chats/{chat_id}/participants/{fake_id}/role",
            json={"role": "moderator"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_cannot_change_admin_role(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.patch(
            f"/chats/{chat_id}/participants/{user_b_id}/role",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self, client: AsyncClient):
        token1, _ = await self._register(client, "user_a")
        _, user_b_id = await self._register(client, "user_b")

        chat = await self._create_group(client, token1, [str(user_b_id)])
        chat_id = chat.json()["id"]

        resp = await client.patch(
            f"/chats/{chat_id}/participants/{user_b_id}/role",
            json={"role": "superadmin"},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert resp.status_code == 422
