# Nass Remote MCP gateway (Netlify)

This is a **secure transport gateway**, not a misleading serverless replacement for Whisper. It relays Model Context Protocol Streamable HTTP requests to the full Python Nass MCP worker (v0.2.1+) running behind its own secure HTTPS endpoint.

## Architecture

```
MCP client ──HTTPS POST Authorization: Bearer <gateway-key>──> Netlify /mcp
   Netlify ──HTTPS POST Authorization: Bearer <backend-key>──> HTTPS-protected Python Nass /mcp
   Python worker ── yt-dlp / YouTube.js / Go extractors ──> YouTube audio
   Python worker ── faster-whisper ──> timestamped transcription
```

Netlify exposes `/health` without credentials. `/health` reports **configuration**, not actual ASR reachability. `/mcp` rejects unauthenticated requests and cannot work before the Python backend is online.

## Variables (Netlify site, *Functions* scope)

| Name | Value |
| --- | --- |
| `NASS_MCP_BEARER_TOKEN` | 256-bit random personal client token, **secret** |
| `NASS_BACKEND_URL` | Full `https://<secure-worker-host>/mcp` endpoint, not localhost |
| `NASS_BACKEND_TOKEN` | Dedicated upstream secret, **secret**; protect upstream with it at the reverse proxy/tunnel |

Never put tokens into `netlify.toml` or your public repository. The backend token must be checked by the worker's outer HTTPS proxy/access layer (the Python MCP app does not yet enforce it itself).

## Deploy

Use Git-backed deployment or `netlify deploy --build --prod` after `netlify link`. Set environment variables in Netlify before deploying. Local build test: `npm test`. The Netlify dashboard integration alone cannot upload code if no deploy/create-deploy action is exposed.

## Security & limitations

- The gateway validates a bearer token in constant time and rate-limits calls.
- The backend URL is a fixed environment variable, validated for HTTPS; input cannot change its host.
- POST JSON only. Streamable HTTP `Accept: application/json, text/event-stream` required. Netlify is stateless; persistent MCP sessions and ASR job state remain with the worker.
- Redirects to another host are refused. Backend communication times out after 52 seconds; long ASR must be submitted as a job and polled in subsequent calls.
- Netlify does not store decoded audio, run local Whisper, or fix IP-based YouTube blocks.
- Client must support supplying Authorization headers. ChatGPT connector onboarding may demand OAuth and must be verified independently before calling this "connected".

## Minimal end-to-end setup with a free temporary tunnel

On a machine that has `Python 3.11+`, FFmpeg and the optional extractors installed:

```bash
cd nass-mcp
pip install -e '.[all,remote]'
export NASS_BACKEND_TOKEN="$(openssl rand -hex 32)"
export NASS_DATA_DIR="$HOME/.local/share/nass-mcp"
nass-backend  # leave running; binds to localhost only
```

In a second terminal, start the *official* `cloudflared` client with `cloudflared tunnel --url http://127.0.0.1:8000`. Record its temporary `https://...trycloudflare.com` URL. The Python worker rejects unauthenticated requests even when the temporary tunnel URL is known. This temporary hostname changes on tunnel restart; a stable hostname requires a separately configured named tunnel/domain.

Deploy the `remote-netlify/` directory to the **existing** Netlify project `nass-mcp-remote` using Git or Netlify CLI. With Netlify CLI, log in and link the project, then set the following in the Netlify dashboard's **Environment variables** section (Functions scope). The keys should be secret where indicated:

1. `NASS_BACKEND_URL` = `https://<actual tunnel hostname>/mcp`
2. `NASS_BACKEND_TOKEN` = the **same** value exported to the Python worker
3. `NASS_MCP_BEARER_TOKEN` = a *different* random token generated with `openssl rand -hex 32`

Run `netlify deploy --build --prod` from `remote-netlify/`. Check `https://nass-mcp-remote.netlify.app/health`; `backendConfigured: true` only means variables were supplied, not that a real ASR call succeeded.

MCP client configuration: URL `https://nass-mcp-remote.netlify.app/mcp`, Authorization header `Bearer <NASS_MCP_BEARER_TOKEN>`, transport Streamable HTTP. Verify with the MCP Inspector `tools/list`, then `nass_health`, then a short public YouTube clip with `mode: audio`. Some clients, including ChatGPT account connector flows, require OAuth-based onboarding and may not accept static bearer headers. In that case an OAuth adapter must be added before calling this a connected ChatGPT plugin.

**Cost boundary:** Netlify's free function quota and a temporary Cloudflare tunnel can incur no compulsory subscription, but an always-on host, power and network resources are still needed for local audio ASR. Unavailability of that host is reported as an upstream error, not silently reclassified as successful transcript retrieval.
