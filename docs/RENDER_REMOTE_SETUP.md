# Nass backend on Render — free trial deployment

This folder contains the *real* Python worker. The Netlify project already live
at https://nass-mcp-remote.netlify.app/health is only an HTTPS transport gateway.

## Prerequisites

- Push the `nass-mcp` **repository root** to a GitHub repository with the Dockerfile
  and `render.yaml` visible at its root. The ZIP must be unpacked before pushing.
- Choose the existing Render workspace `My Workspace` and the `free` plan.
- Render's free instance is 512 MiB/0.1 vCPU; Arabic `tiny` Whisper is an initial
  functionality test, not production-quality Arabic recognition.
- Rendering long YouTube videos or running Whisper on 0.1 CPU may fail or take an
  impractically long time. Record the failure; do not silently return captions as ASR.

## Publish

1. Render Dashboard > New > Blueprint > connect GitHub repository containing `render.yaml`.
   Or New > Web Service > connect repo > Docker > Free > Dockerfile `Dockerfile`.
2. Set `NASS_BACKEND_TOKEN` to a random unique 32-byte token through Render's
   secret environment variable UI. Never put it in Git or chat.
3. Deploy; wait for Render's green status. Render probes GET /healthz (which returns only `ok`, no secrets).
   The app still responds 405 to GET /mcp and 401 to unauthenticated POST /mcp.
4. In Netlify project > Environment Variables (Functions runtime):
   - `NASS_BACKEND_URL=https://<ACTUAL>.onrender.com/mcp`
   - `NASS_BACKEND_TOKEN=<same secret as in Render>`
   - `NASS_MCP_BEARER_TOKEN=<different random 32-byte token>`
   Set the two tokens as secret. Redeploy Netlify so runtime variables apply.
5. Test Netlify `/health` for `backendConfigured: true`. This is only configuration.
6. Test MCP POST with proper `Accept: application/json, text/event-stream`, bearer
   token and JSON-RPC handshake, then `tools/list`, `nass_health`, then short public
   video audio transcription. Store no copied tokens in logs.

## Limitations

The worker's files, cached audio, ASR model, and job transcripts are erased when
Render Free spins down or redeploys. Its 15-minute idle sleep can interrupt jobs;
Netlify imposes a 52-second gateway wait timeout per MCP request. This is a
prototype, not a permanently reliable service. A persistent job store/object
storage and orchestration are future work. Render bandwidth/build overages can
incur fees if a billing method is present: use spend controls and usage dashboard.
