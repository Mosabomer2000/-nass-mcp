"""MCP SDK contract test; exercises client-to-tool protocol in memory."""
import asyncio
from mcp import Client
from nass_mcp.server import mcp


def test_acquisition_report_is_discoverable_and_callable():
    async def check():
        async with Client(mcp, raise_exceptions=True) as client:
            result = await client.call_tool("nass_acquisition_report", {})
            assert not result.is_error
            serialized = " ".join(getattr(item, "text", "") for item in result.content)
            assert "invidious" in serialized or bool(result.structured_content)
    asyncio.run(check())
