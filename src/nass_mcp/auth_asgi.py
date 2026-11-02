"""Strict bearer boundary for the public Nass Render worker.

The worker is directly internet-reachable, so gateway limits must also apply.
The ASGI lifespan fails closed without a configured backend token.
"""
from __future__ import annotations

import hmac
import os
from typing import Any

MAX_MCP_REQUEST_BYTES = 256 * 1024


class ProtectedASGI:
    def __init__(self, app: Any, secret_env: str = "NASS_BACKEND_TOKEN"):
        self.app = app
        self.secret_env = secret_env

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        kind = scope.get("type")
        if kind == "lifespan":
            # Uvicorn's direct Docker entrypoint bypasses remote.main().
            # Do not mark an unconfigured worker ready to accept requests.
            first = await receive()
            if first.get("type") == "lifespan.startup" and not os.environ.get(self.secret_env):
                await send({"type": "lifespan.startup.failed",
                            "message": "NASS_BACKEND_TOKEN is required"})
                return
            initial = [first]

            async def replay_receive() -> dict:
                if initial:
                    return initial.pop(0)
                return await receive()

            await self.app(scope, replay_receive, send)
            return
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if kind != "http":
            return

        path = scope.get("path", "").rstrip("/")
        method = scope.get("method", "")
        if path == "/healthz" and method in ("GET", "HEAD"):
            await self._reply(send, 200, b"ok" if method == "GET" else b"")
            return
        if path != "/mcp":
            await self._reply(send, 404, b"Not found")
            return
        if method != "POST":
            await self._reply(send, 405, b"Method not allowed")
            return

        headers = scope.get("headers", [])
        authorizations = [v for k, v in headers if k.lower() == b"authorization"]
        expected = os.environ.get(self.secret_env, "")
        token = ""
        if len(authorizations) == 1:
            authorization = authorizations[0].decode("latin1")
            token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        if not expected or not token or not hmac.compare_digest(token, expected):
            await self._reply(send, 401, b"Unauthorized")
            return

        lengths = [v for k, v in headers if k.lower() == b"content-length"]
        if len(lengths) > 1:
            await self._reply(send, 400, b"Invalid content length")
            return
        if lengths:
            try:
                length = int(lengths[0])
                if length < 0:
                    raise ValueError()
            except ValueError:
                await self._reply(send, 400, b"Invalid content length")
                return
            if length > MAX_MCP_REQUEST_BYTES:
                await self._reply(send, 413, b"Request too large")
                return

        parts = []
        total = 0
        while True:
            event = await receive()
            if event.get("type") != "http.request":
                return  # Client disconnected; no partial RPC gets dispatched.
            chunk = event.get("body", b"")
            total += len(chunk)
            if total > MAX_MCP_REQUEST_BYTES:
                await self._reply(send, 413, b"Request too large")
                return
            parts.append(chunk)
            if not event.get("more_body", False):
                break

        payload = b"".join(parts)
        replayed = False

        async def replay_body() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)

    @staticmethod
    async def _reply(send: Any, status: int, message: bytes) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": message, "more_body": False})
