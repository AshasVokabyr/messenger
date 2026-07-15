import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class TestErrorFormat:
    async def _register_user(self, client: AsyncClient, login: str = "testuser") -> str:
        resp = await client.post(
            "/auth/register",
            json={"login": login, "password": "secret123"},
        )
        return resp.json()["access_token"]

    @pytest.mark.asyncio
    async def test_http_exception_format(self, client: AsyncClient):
        token = await self._register_user(client)
        response = await client.get(
            "/chats/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body
        assert "request_id" in body
        uuid.UUID(body["request_id"])

    @pytest.mark.asyncio
    async def test_unauthorized_format(self, client: AsyncClient):
        response = await client.get("/chats/")
        assert response.status_code == 401
        body = response.json()
        assert body["detail"] == "Not authenticated"
        assert "request_id" in body
        uuid.UUID(body["request_id"])

    @pytest.mark.asyncio
    async def test_validation_error_format(self, client: AsyncClient):
        response = await client.post("/auth/register", json={})
        assert response.status_code == 422
        body = response.json()
        assert body["detail"] == "Validation error"
        assert "request_id" in body
        uuid.UUID(body["request_id"])
        assert "errors" in body
        assert isinstance(body["errors"], list)
        assert len(body["errors"]) > 0
        for err in body["errors"]:
            assert "field" in err
            assert "message" in err

    @pytest.mark.asyncio
    async def test_internal_error_no_traceback(self):
        @app.get("/_test_500")
        async def _test_500():
            raise RuntimeError("Test internal error")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get("/_test_500")
        assert response.status_code == 500
        body = response.json()
        assert body["detail"] == "Internal server error"
        assert "request_id" in body
        uuid.UUID(body["request_id"])
        assert "traceback" not in body
        assert "exc" not in body
        app.router.routes = [r for r in app.router.routes if r.path != "/_test_500"]

    @pytest.mark.asyncio
    async def test_request_id_is_uuid_on_all_errors(self, client: AsyncClient):
        endpoints = [
            ("GET", "/chats/", {}),
            ("POST", "/chats/group", {"json": {}}),
        ]
        for method, path, kwargs in endpoints:
            if method == "GET":
                response = await client.get(path, **kwargs)
            else:
                response = await client.post(path, **kwargs)
            assert response.status_code in (401, 422)
            body = response.json()
            assert "request_id" in body
            uuid.UUID(body["request_id"])
