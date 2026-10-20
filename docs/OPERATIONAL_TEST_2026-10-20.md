# Nass MCP — 2026-10-20 operational test evidence

## Environment and gates

- Python 3.13.5; real FFmpeg, FFprobe, Node.js and espeak present.
- `mcp`, `yt-dlp`, `youtube-transcript-api`, `pytubefix`, `faster-whisper` not installed.
- YouTube DNS lookup failed; even pip could not retrieve a package from the configured environment.
- Current 39 offline tests: **39 passed**. This is not equivalent to 39 live-provider tests.
- Actual real-world audio/captions fetch: **BLOCKED**, not passed.
- Genuine MCP SDK import/transport: **BLOCKED**, not passed.

## Additional process-level tests that passed

1. Used `espeak` to generate a genuine WAV of spoken English; real `ffprobe` identified media.
2. Submitted a job through the real `JobStore`; the default recognizer intentionally failed.
3. Launched an *executable simulated* whisper.cpp CLI in a separate subprocess. It validated the real 16k mono FFmpeg conversion and emitted a known SRT fixture, **not a recognized transcript**.
4. Verified task persistence after a new `JobStore` instance, paginated results, TXT/JSON/SRT exports, search, and generated actual MP3 excerpt through FFmpeg.
5. Launched the shipped YouTube.js downloader as a real Node subprocess. A local `youtubei.js` **stub** supplied actual encoded audio bytes; output was identical, FFprobe validated playback, and an over-limit stream was rejected and deleted.
6. Exercised the real audio-download job path using a local audio provider fixture.
7. Added regression test against the incorrect `Audio` SDK import, now fixed in v0.2.1.

## Limitations and remaining gates

| Gate | Verdict | Why |
|---|---|---|
| Existing tests | PASS | 35/35 |
| Process-level integrations | PASS (simulated providers) | 4/4 |
| Real YouTube captions | BLOCKED | no DNS, providers absent |
| Real YouTube audio | BLOCKED | no DNS, providers absent |
| Genuine Whisper model recognition | BLOCKED | packages/models absent |
| MCP client↔server handshake | BLOCKED | `mcp` dependency absent |
| Live fallback among upstreams | BLOCKED | all need real upstream access |

The correction to the SDK import is supported by the official MCP Python SDK test suite which imports
`Audio` from `mcp.server.mcpserver.utilities.types`:
https://github.com/modelcontextprotocol/python-sdk/blob/main/tests/server/mcpserver/test_server.py

## Reproduce with a network-enabled installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[all,test]'
python scripts/operational_check.py --live --video 'https://youtu.be/QxC5E44QoZY'
```

A live PASS does not guarantee all videos. Repeat with a video without captions, a long Arabic video, and real models, measuring word error rate against checked reference transcripts.
