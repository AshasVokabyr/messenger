import uuid

import pytest
from httpx import AsyncClient

from app.auth.utils import create_access_token


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        response = await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "secret123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_register_duplicate_login(self, client: AsyncClient):
        await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "secret123"},
        )
        response = await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "secret123"},
        )
        assert response.status_code == 409
        assert "already taken" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_too_short_login(self, client: AsyncClient):
        response = await client.post(
            "/auth/register",
            json={"login": "ab", "password": "secret123"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_too_short_password(self, client: AsyncClient):
        response = await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "12345"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_password_not_stored_in_plaintext(self, client: AsyncClient):
        await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "secret123"},
        )
        response = await client.post(
            "/auth/login",
            json={"login": "testuser", "password": "secret123"},
        )
        assert response.status_code == 200
        from sqlalchemy import select
        from tests.conftest import test_async_session
        from app.models.user import User
        async with test_async_session() as session:
            result = await session.execute(select(User).where(User.login == "testuser"))
            user = result.scalar_one()
            assert user.password_hash != "secret123"
            assert user.password_hash.startswith("$2b$")


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "secret123"},
        )
        response = await client.post(
            "/auth/login",
            json={"login": "testuser", "password": "secret123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post(
            "/auth/register",
            json={"login": "testuser", "password": "secret123"},
        )
        response = await client.post(
            "/auth/login",
            json={"login": "testuser", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        response = await client.post(
            "/auth/login",
            json={"login": "nonexistent", "password": "secret123"},
        )
        assert response.status_code == 401


class TestAuthDependency:
    @pytest.mark.asyncio
    async def test_access_without_token(self, client: AsyncClient):
        response = await client.get("/chats/")
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    @pytest.mark.asyncio
    async def test_access_with_invalid_token(self, client: AsyncClient):
        response = await client.get(
            "/chats/",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired token"

    @pytest.mark.asyncio
    async def test_access_with_malformed_user_id_in_token(self, client: AsyncClient):
        token = create_access_token("not-a-uuid")
        response = await client.get(
            "/chats/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Malformed user ID in token"

    @pytest.mark.asyncio
    async def test_access_with_valid_token_and_own_chats(self, client: AsyncClient):
        reg1 = await client.post(
            "/auth/register",
            json={"login": "user1", "password": "secret123"},
        )
        token1 = reg1.json()["access_token"]

        reg2 = await client.post(
            "/auth/register",
            json={"login": "user2", "password": "secret123"},
        )
        import jwt as pyjwt
        user2_id = uuid.UUID(pyjwt.decode(
            reg2.json()["access_token"],
            options={"verify_signature": False},
        )["sub"])

        create_chat = await client.post(
            "/chats/group",
            json={"name": "test-chat", "participant_ids": [str(user2_id)]},
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert create_chat.status_code == 201
        chat_id = create_chat.json()["id"]

        response = await client.get(
            "/chats/",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert response.status_code == 200
        chats = response.json()
        assert any(c["id"] == chat_id for c in chats)
        assert any(c["name"] == "test-chat" for c in chats)
