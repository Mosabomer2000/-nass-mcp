"""Dependency-light bearer authentication for Nass's ASGI worker.

Authentication is enforced at the worker, not just at the Netlify gateway. The
MCP SDK app's own lifespan is delegated unchanged (important for MCP v2).
"""
from __future__ import annotations

import hmac
import os
from typing import Any


class ProtectedASGI:
    def __init__(self, app: Any, secret_env: str = "NASS_BACKEND_TOKEN"):
        self.app = app
        self.secret_env = secret_env

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Public Render readiness probe: constant answer, no secrets or model load.
        if scope.get("path", "").rstrip("/") == "/healthz" and scope.get("method") in ("GET", "HEAD"):
            await self._reply(send, 200, b"ok" if scope.get("method") == "GET" else b"")
            return
        # Do not surface any other web routes exposed by the SDK in the future.
        if scope.get("path", "").rstrip("/") != "/mcp":
            await self._reply(send, 404, b"Not found")
            return
        if scope.get("method") != "POST":
            await self._reply(send, 405, b"Method not allowed")
            return
        expected = os.environ.get(self.secret_env, "")
        authorization = next((v.decode("latin1") for k, v in scope.get("headers", [])
                              if k.lower() == b"authorization"), "")
        token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        if not expected or not token or not hmac.compare_digest(token, expected):
            await self._reply(send, 401, b"Unauthorized")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reply(send: Any, status: int, message: bytes) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": message, "more_body": False})
