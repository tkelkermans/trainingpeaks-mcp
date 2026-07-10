"""Tests for the shared ASGI app (src/tp_mcp/http_app.py) and the push-cookie CLI guards.

Uses httpx.ASGITransport, which does NOT fire ASGI lifespan events. That deliberately
exercises the lazy-start fallback in _ManagerLifecycle.ensure_started() rather than the
lifespan path (covered separately by TestLifespan).
"""

from unittest.mock import patch

import httpx
import pytest

SECRET = "test-secret-9f3a7c21"

JSON_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """Build a minimal JSON-RPC 2.0 request body."""
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


@pytest.fixture
def app(monkeypatch):
    """Build the app with MCP_AUTH_SECRET set before create_app() is called."""
    monkeypatch.setenv("MCP_AUTH_SECRET", SECRET)
    from tp_mcp.http_app import create_app

    return create_app()


@pytest.fixture
async def client(app):
    """httpx client talking to the app over ASGITransport (no lifespan)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestToolsList:
    """tools/list should succeed via either supported auth mechanism."""

    @pytest.mark.asyncio
    async def test_via_path_secret(self, client):
        response = await client.post(f"/mcp/{SECRET}", json=_rpc("tools/list"), headers=JSON_RPC_HEADERS)

        assert response.status_code == 200
        tools = response.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "tp_get_workouts" in names
        assert len(names) >= 50

    @pytest.mark.asyncio
    async def test_via_bearer_header(self, client):
        headers = {**JSON_RPC_HEADERS, "Authorization": f"Bearer {SECRET}"}
        response = await client.post("/mcp", json=_rpc("tools/list"), headers=headers)

        assert response.status_code == 200
        assert "tools" in response.json()["result"]


class TestAuthRejection:
    """Requests without a valid secret must be rejected."""

    @pytest.mark.asyncio
    async def test_wrong_path_secret_returns_401(self, client):
        response = await client.post("/mcp/wrong-secret", json=_rpc("tools/list"), headers=JSON_RPC_HEADERS)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(self, client):
        response = await client.post("/mcp", json=_rpc("tools/list"), headers=JSON_RPC_HEADERS)
        assert response.status_code == 401


class TestCreateAppFailsClosed:
    """create_app() must refuse to start without a configured secret."""

    def test_raises_when_secret_unset(self, monkeypatch):
        monkeypatch.delenv("MCP_AUTH_SECRET", raising=False)
        from tp_mcp.http_app import create_app

        with pytest.raises(RuntimeError):
            create_app()


class TestInitializeRoundTrip:
    """Full JSON-RPC initialize handshake through the transport."""

    @pytest.mark.asyncio
    async def test_initialize_returns_server_info(self, client):
        params = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        }
        response = await client.post(f"/mcp/{SECRET}", json=_rpc("initialize", params), headers=JSON_RPC_HEADERS)

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["serverInfo"]["name"] == "trainingpeaks-mcp"


class TestLifespan:
    """Entering/exiting the Starlette lifespan context should be clean (manager starts, then stops)."""

    @pytest.mark.asyncio
    async def test_lifespan_enter_exit(self, app):
        async with app.router.lifespan_context(app):
            pass


class TestHealth:
    """GET / health check used by uptime monitors."""

    @pytest.mark.asyncio
    async def test_health_ok(self, client):
        response = await client.get("/")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "trainingpeaks-mcp"


class TestPushCookieGuards:
    """cmd_push_cookie must never shell out to vercel with a bad or unvalidated cookie."""

    def test_aborts_when_browser_extraction_fails(self):
        from tp_mcp.auth.browser import BrowserCookieResult
        from tp_mcp.cli import cmd_push_cookie

        with (
            patch("tp_mcp.cli.extract_tp_cookie") as mock_extract,
            patch("subprocess.run", side_effect=AssertionError("subprocess.run must not be called")),
        ):
            mock_extract.return_value = BrowserCookieResult(success=False, message="No browser found")

            exit_code = cmd_push_cookie(from_browser="chrome", target="production")

        assert exit_code == 1

    def test_aborts_when_cookie_fails_validation(self):
        from tp_mcp.auth.browser import BrowserCookieResult
        from tp_mcp.auth.validator import AuthResult, AuthStatus
        from tp_mcp.cli import cmd_push_cookie

        with (
            patch("tp_mcp.cli.extract_tp_cookie") as mock_extract,
            patch("tp_mcp.cli.validate_auth_sync") as mock_validate,
            patch("subprocess.run", side_effect=AssertionError("subprocess.run must not be called")),
        ):
            mock_extract.return_value = BrowserCookieResult(success=True, cookie="fake-cookie", browser="chrome")
            mock_validate.return_value = AuthResult(status=AuthStatus.INVALID, message="Cookie expired")

            exit_code = cmd_push_cookie(from_browser="chrome", target="production")

        assert exit_code == 1
