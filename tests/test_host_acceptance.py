"""Test source validation and sanitized MCP SDK results for the acceptance tool."""
import json
from types import SimpleNamespace
import pytest
from nass_mcp.host_acceptance import unwrap, run_acceptance


def test_unwrap_structured_result():
    data = SimpleNamespace(structured_content={"result":{"job_id":"a"*32,"state":"queued"}}, content=[])
    assert unwrap(data)["state"] == "queued"


def test_unwrap_text_result():
    data = SimpleNamespace(structured_content=None,
                           content=[SimpleNamespace(text=json.dumps({"result":{"state":"failed","job_id":"b"*32}}))])
    assert unwrap(data)["job_id"] == "b"*32


def test_unwrap_fails_closed_on_invalid_payload():
    with pytest.raises(RuntimeError):
        unwrap(SimpleNamespace(structured_content={"random":"text"},content=[]))


@pytest.mark.asyncio
async def _unused():
    pass


def test_host_acceptance_rejects_untrusted_video_url_before_io():
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(run_acceptance(youtube="http://127.0.0.1/file", language="ar"))


def test_host_acceptance_requires_exactly_one_input():
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(run_acceptance())
    with pytest.raises(ValueError):
        asyncio.run(run_acceptance(youtube="QxC5E44QoZY", local_file="x.wav"))


def test_host_acceptance_requires_bounded_timeout():
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(run_acceptance(local_file="x.wav", max_wait_seconds=999999))
