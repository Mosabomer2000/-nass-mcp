"""Run the real Nass audio/ASR engine behind an authenticated remote MCP gateway.

This worker runs on a full Python host; NOT inside Netlify Functions.
Run: NASS_BACKEND_TOKEN=... nass-backend
If published over HTTPS, the edge proxy must preserve the /mcp path and bearer
header. Protect the outbound HTTPS endpoint with its own access rules as well.
"""
from __future__ import annotations
import os

from mcp.server.transport_security import TransportSecuritySettings
from .auth_asgi import ProtectedASGI
from .server import mcp

# Requests arriving through a TLS tunnel carry the external hostname. Disable
# localhost-only Host checking here: the dedicated bearer guard is mandatory.
_inner_app = mcp.streamable_http_app(
    json_response=True,
    stateless_http=True,
    host="0.0.0.0",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
app = ProtectedASGI(_inner_app)


def main() -> None:
    if not os.getenv("NASS_BACKEND_TOKEN"):
        raise SystemExit("NASS_BACKEND_TOKEN must be set before running the remote backend")
    import uvicorn
    uvicorn.run(app, host=os.getenv("NASS_HOST", "127.0.0.1"),
                port=int(os.getenv("NASS_PORT", "8000")), proxy_headers=False)


if __name__ == "__main__":
    main()
