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
