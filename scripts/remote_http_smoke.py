"""Safe remote MCP Streamable HTTP smoke test against an authorized worker.

No paid API, YouTube downloads, private audio, or secrets are printed.
The token is supplied ONLY through NASS_BACKEND_TOKEN in the environment.

    NASS_BACKEND_TOKEN=... python -m scripts.remote_http_smoke \
      --url http://127.0.0.1:18080/mcp
"""
from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request(url: str, *, token: str | None = None, method: str = "POST",
            payload: dict | None = None, timeout: int = 20) -> tuple[int, dict | None]:
    headers = {"Accept": "application/json, text/event-stream"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, method=method, headers=headers, data=body)
    try:
        with urlopen(req, timeout=timeout) as result:
            response = result.read(512 * 1024)
            status = result.status
    except HTTPError as e:
        status = e.code
        response = e.read(8192)
    try:
        parsed = json.loads(response)
    except (ValueError, UnicodeError):
        parsed = None
    return status, parsed


def smoke(url: str, token: str) -> dict:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.path != "/mcp" or not parts.hostname:
        raise ValueError("MCP URL must be http(s) and end in /mcp")
    if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote worker smoke tests require HTTPS")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Do not supply URL credentials or query parameters")
    if not token:
        raise ValueError("NASS_BACKEND_TOKEN must be set in the environment")

    health_url = url.rsplit("/mcp", 1)[0] + "/healthz"
    health, _ = request(health_url, method="GET")
    unauthorized, _ = request(url, payload={
        "jsonrpc": "2.0", "id": 1, "method": "ping",
    })
    no_get, _ = request(url, method="GET", token=token)
    if health != 200 or unauthorized != 401 or no_get != 405:
        raise RuntimeError("Worker health/authentication/method checks failed")

    headers = token
    init_status, init = request(url, token=headers, payload={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "nass-render-smoke", "version": "1"},
        },
    })
    if init_status != 200 or not isinstance(init, dict) or not isinstance(init.get("result"), dict):
        raise RuntimeError("Authenticated MCP initialization did not return a valid result")

    tool_status, tools = request(url, token=headers, payload={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        "params": {},
    })
    if tool_status != 200 or not isinstance(tools, dict):
        raise RuntimeError("Authenticated MCP tools/list failed")
    result = tools.get("result")
    found = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(found, list) or "nass_health" not in {
        entry.get("name") for entry in found if isinstance(entry, dict)
    }:
        raise RuntimeError("MCP tool discovery did not register Nass health")

    call_status, called = request(url, token=headers, payload={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "nass_health", "arguments": {}},
    })
    if call_status != 200 or not isinstance(called, dict) or \
       not isinstance(called.get("result"), dict) or called["result"].get("isError") is True:
        raise RuntimeError("Authenticated read-only MCP tool call failed")
    return {
        "passed": True,
        "public_health_status": health,
        "unauthorized_rpc_status": unauthorized,
        "get_rpc_status": no_get,
        "initialize_status": init_status,
        "tool_discovery_status": tool_status,
        "nass_health_status": call_status,
        "discovered_tool_count": len(found),
        "asr_accuracy_verified": False,
        "youtube_audio_acquisition_verified": False,
        "secrets_or_transcripts_in_report": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18080/mcp")
    args = parser.parse_args()
    output = smoke(args.url, os.environ.get("NASS_BACKEND_TOKEN", ""))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
