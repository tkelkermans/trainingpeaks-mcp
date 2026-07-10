"""Shared ASGI app exposing the MCP server over streamable HTTP.

Serves both local HTTP mode (``tp-mcp serve --transport http``) and the
Vercel serverless entry point (``api/index.py``).
"""

import contextlib
import hmac
import os
from collections.abc import AsyncIterator

import anyio
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, get_route_path
from starlette.types import Receive, Scope, Send

from tp_mcp.server import server

AUTH_SECRET_ENV = "MCP_AUTH_SECRET"


class _ManagerLifecycle:
    """Starts the session manager exactly once, via lifespan or lazily on first request.

    The Starlette lifespan is the normal path: it starts the manager on enter and
    closes it on exit. The lazy path (``ensure_started`` from the request handler)
    exists for platforms that never fire ASGI lifespan events. A lazy-started
    manager is intentionally never exited: on serverless the runtime freezes or
    kills the process rather than shutting it down gracefully, and in stateless
    mode each request's tasks complete with the request, so nothing is pending
    when the process dies.
    """

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager
        self._lock = anyio.Lock()
        self._started = False
        self._stack: contextlib.AsyncExitStack | None = None

    async def ensure_started(self) -> None:
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            stack = contextlib.AsyncExitStack()
            await stack.enter_async_context(self._manager.run())
            self._stack = stack
            self._started = True

    @contextlib.asynccontextmanager
    async def lifespan(self, app: Starlette) -> AsyncIterator[None]:
        await self.ensure_started()
        try:
            yield
        finally:
            # manager.run() is once-per-instance, so leave _started True after close.
            if self._stack is not None:
                stack, self._stack = self._stack, None
                await stack.aclose()


def _is_authorized(scope: Scope, secret: str) -> bool:
    """Check the secret in the URL path (first segment after the /mcp mount) or a Bearer header.

    Uses get_route_path() so the path is taken relative to the /mcp mount's root_path.
    Starlette's Mount does not rewrite scope["path"]; it only sets scope["root_path"],
    so reading scope["path"] directly would always see the literal "mcp" segment.
    """
    candidates: list[str] = []
    path = get_route_path(scope).strip("/")
    if path:
        candidates.append(path.split("/", 1)[0])
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            auth = value.decode("latin-1")
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
                if token:
                    candidates.append(token)
            break
    return any(hmac.compare_digest(candidate, secret) for candidate in candidates)


def create_app(*, require_auth: bool = True) -> Starlette:
    """Build the Starlette app. Fails closed if auth is required but no secret is configured."""
    secret = os.environ.get(AUTH_SECRET_ENV, "")
    if require_auth and not secret:
        raise RuntimeError(
            f"{AUTH_SECRET_ENV} is not set; refusing to start an unauthenticated HTTP server. "
            "Generate a secret with: python -c 'import secrets; print(secrets.token_urlsafe(32))' "
            f"and set it as the {AUTH_SECRET_ENV} environment variable."
        )

    # No security_settings: the defaults disable Host/Origin checks, which is
    # required behind Vercel's proxy where the public host differs.
    manager = StreamableHTTPSessionManager(app=server, event_store=None, json_response=True, stateless=True)
    lifecycle = _ManagerLifecycle(manager)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "trainingpeaks-mcp"})

    class _MCPEndpoint:
        """Raw ASGI endpoint: authenticates, then hands the request to the transport.

        Defined as a callable object rather than a function so Starlette's Route
        passes it through as a raw ASGI app (it wraps plain functions as
        request/response handlers, which would break the transport's protocol).
        """

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if secret and not _is_authorized(scope, secret):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
            await lifecycle.ensure_started()
            await manager.handle_request(scope, receive, send)

    mcp_endpoint = _MCPEndpoint()

    return Starlette(
        routes=[
            Route("/", health, methods=["GET"]),
            # Exact "/mcp" (no trailing slash) for the Bearer-token flow: a bare Mount
            # would 307-redirect it to "/mcp/", which POST clients do not follow.
            Route("/mcp", mcp_endpoint, methods=["GET", "POST", "DELETE"]),
            # "/mcp/<secret>" for the URL-path auth flow.
            Mount("/mcp", app=mcp_endpoint),
        ],
        lifespan=lifecycle.lifespan,
    )
