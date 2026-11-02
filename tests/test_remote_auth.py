"""Integration tests for the zero-dependency remote worker bearer guard."""
import asyncio
import os
from unittest.mock import patch
from nass_mcp.auth_asgi import ProtectedASGI


def run_case(path="/mcp", method="POST", auth=None, env="secret"):
    seen=[]
    async def inner(scope, receive, send):
        seen.append("inner")
        await send({"type":"http.response.start", "status":200, "headers":[]})
        await send({"type":"http.response.body", "body":b"ok"})
    async def receive(): return {"type":"http.request", "body":b"", "more_body":False}
    async def send(event): seen.append(event)
    headers = [] if not auth else [(b"authorization", auth.encode("latin1"))]
    scope={"type":"http", "path":path, "method":method, "headers":headers}
    with patch.dict(os.environ, {"NASS_BACKEND_TOKEN":env} if env else {}, clear=True):
        asyncio.run(ProtectedASGI(inner)(scope,receive,send))
    return seen


def test_backend_accepts_valid_token():
    assert "inner" in run_case(auth="Bearer secret")

def test_backend_refuses_wrong_token():
    events=run_case(auth="Bearer invalid")
    assert events[0]["status"] == 401 and "inner" not in events

def test_backend_refuses_no_token():
    assert run_case()[0]["status"] == 401

def test_backend_refuses_unconfigured_token():
    assert run_case(auth="Bearer secret", env="")[0]["status"] == 401

def test_backend_only_exposes_mcp():
    assert run_case(path="/internal",auth="Bearer secret")[0]["status"] == 404

def test_backend_post_only():
    assert run_case(method="GET", auth="Bearer secret")[0]["status"] == 405


def test_health_probe_is_public_and_constant():
    events = run_case(path="/healthz", method="GET", env="")
    assert events[0]["status"] == 200
    assert events[1]["body"] == b"ok"

def test_health_probe_does_not_expose_other_routes():
    assert run_case(path="/metrics", method="GET", env="")[0]["status"] == 404


def test_lifespan_startup_rejects_missing_worker_configuration():
    responses = []
    forwarded = []
    async def inner(scope, receive, send):
        forwarded.append(True)
        await receive()
        await send({"type": "lifespan.startup.complete"})
    async def receive():
        return {"type": "lifespan.startup"}
    async def send(item):
        responses.append(item)
    with patch.dict(os.environ, {}, clear=True):
        asyncio.run(ProtectedASGI(inner)(
            {"type": "lifespan"}, receive, send))
    assert responses[0]["type"] == "lifespan.startup.failed"
    assert forwarded == []


def test_lifespan_startup_delegates_to_sdk_when_configured():
    responses = []
    forwarded = []
    async def inner(scope, receive, send):
        forwarded.append(await receive())
        await send({"type": "lifespan.startup.complete"})
    async def receive():
        return {"type": "lifespan.startup"}
    async def send(item):
        responses.append(item)
    with patch.dict(os.environ, {"NASS_BACKEND_TOKEN": "ci-test-token"}, clear=True):
        asyncio.run(ProtectedASGI(inner)(
            {"type": "lifespan"}, receive, send))
    assert forwarded == [{"type": "lifespan.startup"}]
    assert responses[0]["type"] == "lifespan.startup.complete"


def test_reject_large_post_even_without_content_length():
    from nass_mcp.auth_asgi import MAX_MCP_REQUEST_BYTES
    responses = []
    forwarded = []
    messages = [
        {"type": "http.request", "body": b"x" * 140_000, "more_body": True},
        {"type": "http.request", "body": b"y" * 140_000, "more_body": False},
    ]
    async def inner(scope, receive, send):
        forwarded.append(True)
    async def receive():
        return messages.pop(0)
    async def send(item):
        responses.append(item)
    scope = {"type": "http", "method": "POST", "path": "/mcp",
             "headers": [(b"authorization", b"Bearer ci-test-token")]}
    with patch.dict(os.environ, {"NASS_BACKEND_TOKEN": "ci-test-token"}, clear=True):
        asyncio.run(ProtectedASGI(inner)(scope, receive, send))
    assert 280_000 > MAX_MCP_REQUEST_BYTES
    assert responses[0]["status"] == 413
    assert forwarded == []


def test_duplicate_authorization_headers_rejected():
    responses = []
    forwarded = []
    async def inner(scope, receive, send):
        forwarded.append(True)
    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}
    async def send(item):
        responses.append(item)
    scope = {"type": "http", "method": "POST", "path": "/mcp",
             "headers": [(b"authorization", b"Bearer ci-test-token")] * 2}
    with patch.dict(os.environ, {"NASS_BACKEND_TOKEN": "ci-test-token"}, clear=True):
        asyncio.run(ProtectedASGI(inner)(scope, receive, send))
    assert responses[0]["status"] == 401
    assert forwarded == []
