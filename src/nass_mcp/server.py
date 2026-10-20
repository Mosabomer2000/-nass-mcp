"""MCP v2 endpoint. By default this only binds locally; secure reverse proxy is required online."""
from __future__ import annotations

import json
import os
from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.types import Audio

from .core import Engine, JobStore, get_video_id, health, safe_error

mcp = MCPServer(
    "Nass — Resilient YouTube Transcription",
    version="0.3.1",
    instructions=(
        "Use nass_start_transcription with mode='audio' when actual spoken sound must be "
        "recognized, not merely subtitle text. Poll nass_job_status, then page through "
        "nass_get_transcript. Treat automatic recognition as fallible: preserve the "
        "source label, timestamp, and uncertainties when using text as research evidence."
    ),
)
engine = Engine()
jobs = JobStore(engine)


@mcp.tool()
def nass_health() -> dict:
    """Inspect availability of independent caption/audio/ASR backends; never claim success from installation alone."""
    return health()


@mcp.tool()
def nass_start_transcription(video_url: str, language: str = "ar", mode: str = "auto") -> dict:
    """Queue a YouTube transcription. auto=prefer captions, audio=recognize original audio,
    captions=captions only, verify=run audio ASR independently and provide both for comparison.
    Always prefer 'audio' for no-captions videos or when verifying quoted speech.
    """
    try:
        return jobs.submit(video_url, language, mode)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_start_local_file(filename: str, language: str = "ar") -> dict:
    """Transcribe a media file inside configured NASS_MEDIA_DIR, bypassing YouTube completely."""
    try:
        return jobs.submit(filename, language, "audio", local=True)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_job_status(job_id: str) -> dict:
    """Get queued/running/completed/failed status and the precise fallback attempt ledger."""
    try:
        return jobs.get_status(job_id)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_get_transcript(job_id: str, start_segment: int = 0,
                        count: int = 60, with_timestamps: bool = True) -> dict:
    """Read long transcripts in reliable pages; next_segment identifies the next page."""
    try:
        return jobs.read(job_id, start_segment, count, with_timestamps)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_search_transcript(job_id: str, query: str, max_matches: int = 15,
                           context_segments: int = 1) -> dict:
    """Search complete stored transcript; return precise quotes/timestamps and source links.
    Arabic diacritics and common alef variants are normalized for retrieval only.
    """
    try:
        return jobs.search(job_id, query, max_matches, context_segments)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_export(job_id: str, output_format: str = "srt") -> dict:
    """Export transcript as SRT, TXT or JSON on the server, for later sharing/analysis."""
    try:
        return jobs.export(job_id, output_format)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_audio_excerpt(job_id: str, start_seconds: float, duration_seconds: float = 15):
    """Return an audio Content block containing up to 45 seconds of actual spoken audio.
    Useful for directly checking critical quotations. Client audio support varies.
    """
    try:
        return Audio(path=jobs.make_audio_clip(job_id, start_seconds, duration_seconds))
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_start_audio_download(video_url: str) -> dict:
    """Queue an audio-only download without captions or speech recognition; poll job status.
    Better suited than the synchronous tool for long videos.
    """
    try:
        return jobs.submit_audio_download(video_url)
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc)}


@mcp.tool()
def nass_download_original_audio(video_url: str) -> dict:
    """Obtain an actual audio media file on the MCP host, without using any captions.
    A synchronous download is appropriate for relatively short public videos.
    The returned file path is server-local and never implies user-side download.
    """
    attempts = []
    try:
        video_id = get_video_id(video_url)
        audio, backend = engine.acquire_audio(video_id, engine.root / "audio-only" / video_id, attempts)
        duration = engine.check_audio(audio)
        return {"ok": True, "video_id": video_id, "method": backend,
                "duration_seconds": duration, "file_on_server": str(audio),
                "size_bytes": audio.stat().st_size, "attempts": attempts}
    except Exception as exc:
        return {"ok": False, "error": safe_error(exc), "attempts": attempts}


def main() -> None:
    transport = os.environ.get("NASS_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    elif transport == "http":
        host = os.environ.get("NASS_HOST", "127.0.0.1")
        # Deliberately fail closed when trying to expose an unauthenticated MCP server.
        if host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("NASS_UNSAFE_PUBLIC_HTTP") != "1":
            raise SystemExit("Unsafe public bind refused: keep localhost and put authentication on an HTTPS reverse proxy")
        mcp.run(transport="streamable-http", host=host,
                port=int(os.environ.get("NASS_PORT", "8000")),
                json_response=True, stateless_http=True)
    else:
        raise SystemExit("NASS_TRANSPORT must be stdio or http")


if __name__ == "__main__":
    main()
