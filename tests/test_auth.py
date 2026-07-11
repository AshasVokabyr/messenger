import pytest
from httpx import AsyncClient


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
