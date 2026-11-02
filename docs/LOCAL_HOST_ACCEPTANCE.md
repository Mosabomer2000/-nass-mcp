# Nass v0.5 — operational gate and local worker

## Evidence as of 2026-11-02

* The initial public GitHub runner failed on both captions and audio for video
  `jNQXAC9IVRw` because YouTube responded with bot-check/login-required errors.
* This does NOT establish a general YouTube outage or that captions are absent.
* The original and new offline regression cases run on Python 3.11 and 3.12;
  the failing media-host probe is a separate and intentionally strict gate.
* PO-token support is an **optional experimental test**, not a guarantee against
  IP-level blocking. No cookies, login credentials or paid transcription service
  are used in these CI runs.

## Local worker (recommended for free, authorized use)

Choose a machine you control and can keep running for the duration of the job.
Python 3.11 or 3.12, FFmpeg/ffprobe and Node >=22 (or Deno >=2) are required.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[all,remote]'
python -m pytest -q
nass-doctor
export NASS_WHISPER_MODEL=small
export NASS_DEVICE=cpu
export NASS_COMPUTE_TYPE=int8
# stdio mode; do not expose unauthenticated /mcp publicly
nass-mcp
```

Optional proof-of-origin provider installation **on an operator-controlled machine**:

```bash
pip install 'bgutil-ytdlp-pot-provider==2.0.2'
docker run --name nass-pot --rm -d --init \
  -p 127.0.0.1:4416:4416 \
  brainicism/bgutil-ytdlp-pot-provider:2.0.2-node
export NASS_ENABLE_MWEB_POT=1
```

Check `yt-dlp -v <public-video-url>` locally to confirm the provider was loaded
and invoked. The provider's server is unauthenticated; **never publish port 4416
on a public interface**. Confirm the image and dependencies yourself.

## Acceptance with real audio

For a short public, accessible video:

```bash
python scripts/live_smoke.py 'https://youtu.be/VIDEO_ID' \
  --mode audio --language ar --output actual-asr.json
```

A successful gate requires:
1. A validated genuine audio stream with a documented source backend.
2. A local ASR backend actually executing and returning timestamped words.
3. A transcript with no empty/missing portions inconsistent with audible speech.
4. Manual comparison against real audio, especially critical Arabic terms.
5. A successful MCP SDK call to `nass_start_transcription`, `nass_job_status`
   and `nass_get_transcript` (including pagination).

A successful **captions-only** job is not evidence of audio acquisition or ASR.
The model may be slow on CPU; pretrained weights may require a one-time download.
Free software is not equivalent to a guaranteed free always-on remote host.

## Error diagnosis

`nass_job_diagnostics(job_id)` returns sanitized categories, not raw provider
logs. `youtube_access_challenge` differs from `captions_unavailable`; do not
claim subtitles are absent when the network has been blocked.

The GitHub live workflow is restricted to acquisition-probe source changes and
manual dispatch to avoid repeated unwanted public YouTube requests. It captures
sanitized evidence but cannot validate the end-to-end Whisper workflow.

Official references:
* https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
* https://github.com/Brainicism/bgutil-ytdlp-pot-provider
* https://github.com/yt-dlp/yt-dlp/wiki/EJS
