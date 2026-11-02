"""Bounded live acquisition probe. Does NOT claim transcription/ASR success.

Runs explicitly against one short public YouTube video, without credentials.
Writes a report after each step so interrupted runs retain diagnostic evidence.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from nass_mcp.core import Engine, get_video_id, safe_error

VIDEO_ID = get_video_id(os.environ.get("NASS_PROBE_VIDEO", "jNQXAC9IVRw"))
OUT = Path(os.environ.get("NASS_PROBE_REPORT", "nass-live-acquisition.json"))
ROOT = Path(os.environ.get("NASS_PROBE_DATA", "/tmp/nass-probe"))
report = {"video_id": VIDEO_ID, "caption": None, "audio": None,
          "message": "Live network probe only. ASR and MCP host deployment are NOT verified."}


def save():
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


def main():
    engine = Engine(ROOT)
    work = ROOT / "live-probe"
    work.mkdir(parents=True, exist_ok=True)
    save()
    attempts = []
    start = time.monotonic()
    try:
        captions = engine.get_captions(VIDEO_ID, "auto", work, attempts)
        report["caption"] = {"success": bool(captions),
                             "source": captions[1] if captions else None,
                             "segments": len(captions[0]) if captions else 0,
                             "attempts": attempts.copy(),
                             "elapsed_seconds": round(time.monotonic() - start, 2)}
    except Exception as exc:
        report["caption"] = {"success": False, "error": safe_error(exc),
                             "attempts": attempts.copy()}
    save()
    start = time.monotonic()
    try:
        path = engine.ytdlp_audio(VIDEO_ID, work / "direct-audio", "default")
        duration = engine.check_audio(path)
        report["audio"] = {"success": True, "source": "yt-dlp/default",
                           "duration_seconds": duration,
                           "size_bytes": path.stat().st_size,
                           "elapsed_seconds": round(time.monotonic() - start, 2)}
    except Exception as exc:
        report["audio"] = {"success": False, "source": "yt-dlp/default",
                           "error": safe_error(exc),
                           "elapsed_seconds": round(time.monotonic() - start, 2)}
    report["acquisition_succeeded"] = bool(
        report.get("caption", {}).get("success") or report.get("audio", {}).get("success")
    )
    save()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["acquisition_succeeded"]:
        raise SystemExit("Live acquisition failed; see the saved provider evidence")


if __name__ == "__main__":
    main()
