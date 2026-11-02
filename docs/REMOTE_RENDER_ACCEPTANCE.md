# Nass Remote MCP / Render — deployment and acceptance gate

**Checked 2026-11-03 (Asia/Riyadh). This is an operator runbook, not proof of production readiness.**

## Installed topology and version drift

- Render workspace: My Workspace; service: nass-audio-worker.
- Dashboard: https://dashboard.render.com/web/srv-dbbjs75g1s2s7397r1d0
- Public address: https://nass-audio-worker.onrender.com/mcp
- Render branch: main, automatic deployment OFF, region Frankfurt, single instance, free plan.
- Render's most recent live deployment: 2026-10-20, commit
  6497320e4e89fb1ba419f65fd9674cd1d12cb108 (Nass v0.3.2).
- Netlify site: nass-mcp-remote, production deployment 2026-10-20, two functions
  (/health and /mcp). Dashboard: https://app.netlify.com/projects/nass-mcp-remote
- v0.5 work is in PR #2, not merged and NOT installed on these production endpoints.
- The existing Render service currently reports an EMPTY healthCheckPath even
  though render.yaml declares /healthz. Set the actual service health check to
  /healthz in the Render dashboard when preparing a controlled deployment.
  A green deploy status is not an authenticated MCP or ASR acceptance result.

## Hard runtime limits

- Render recorded a memory limit of approximately 536,870,900 bytes
  (512 MiB) on 2026-10-20. Logged service memory was far lower but those
  measurements did not prove actual Whisper inference occurred there.
- A successful GitHub-hosted 30-minute natural conversation with the small
  CPU/int8 model recorded approximately 1.76 GiB lifetime peak process RSS.
  That workload is NOT demonstrably safe on a 512 MiB Render instance.
- The Dockerfile explicitly defaults to NASS_WHISPER_MODEL=tiny,
  NASS_BEAM_SIZE=1, NASS_MAX_DURATION_SEC=1200, and one pending job.
  These limits are conservative experiments, NOT quality settings for
  30-minute Arabic lectures.
- Render free storage is ephemeral; ASR jobs, model downloads and source
  media may disappear after recycling. Pending jobs can be interrupted.
- Netlify /mcp forwards bounded JSON requests to the authenticated worker.
  A 52-second proxy timeout is intended for short RPCs: submit and poll
  long jobs separately. This does not guarantee a long job can survive a
  Render sleep/restart.
- The existing Netlify deployment being marked ready does not establish that
  it currently reaches a healthy or authenticated Render backend.

## Remote security properties of the development branch

1. At Uvicorn startup, a missing NASS_BACKEND_TOKEN fails the ASGI lifespan.
   This closes a gap where launching uvicorn directly bypassed the token
   check in the nass-backend CLI function.
2. Every direct POST /mcp checks the worker bearer token (not just the Netlify
   gateway's separate bearer secret); duplicate Authorization headers fail.
3. The worker enforces a 256-KiB JSON-RPC body limit even when Content-Length
   is missing. Public GET /healthz is intentionally constant.
4. WebSocket upgrades and unknown web paths cannot reach the MCP SDK.
5. Never put real access tokens in logs, GitHub Actions, Render environment
   example values, or chat. CI uses its own disposable test credential.

Security checks do not supply OAuth. ChatGPT connectors that require OAuth
will need a separately tested compliant login/authorization layer; static
bearer support MUST NOT be assumed.

## Automated validation on a disposable Docker container

The dedicated workflow .github/workflows/render-remote-ci.yml builds the
repository's actual Dockerfile, runs a container bound to 127.0.0.1, then
probes the HTTP entrypoint using a temporary CI-only token:

- GET /healthz returns 200
- unauthenticated POST /mcp returns 401
- GET /mcp returns 405
- authenticated JSON-RPC initialize succeeds
- authenticated tools/list discovers nass_health
- authenticated tools/call of nass_health succeeds

To reproduce on your own trusted development machine:

    docker build -t nass-render-smoke .
    docker run -d --rm --name nass-render-local \
      -p 127.0.0.1:18080:10000 \
      -e NASS_BACKEND_TOKEN="$NASS_BACKEND_TOKEN" \
      nass-render-smoke
    python -m scripts.remote_http_smoke \
      --url http://127.0.0.1:18080/mcp
    docker stop nass-render-local

Set NASS_BACKEND_TOKEN from a password manager or a securely generated local
secret before these commands. HTTP is allowed ONLY on loopback for this probe.
For public remote hosts, the probe requires HTTPS.

Do NOT infer YouTube acquisition, Arabic lexical accuracy, free-tier memory
capacity or ChatGPT OAuth compatibility from success here.

## Safe production release order

1. Keep Render production branch main unchanged while PR #2 is under test.
2. Pass the full offline Python and browser tests plus Docker HTTP smoke.
3. On a suitably provisioned staging host, verify a real authorized short
   YouTube video -> audio -> ASR -> MCP transcript, then a longer recording.
4. Prove peak memory, worker survival, startup time and expected cost on the
   TARGET host, not just GitHub Actions runners.
5. Apply /healthz as the actual Render service health-check path.
6. Confirm the worker's NASS_BACKEND_TOKEN is set, and Netlify's configured
   NASS_BACKEND_TOKEN matches it; NASS_MCP_BEARER_TOKEN must be separate.
7. Only then merge/deploy in a controlled window and re-check the external
   HTTPS MCP endpoint; do not auto-publish a validation branch.
