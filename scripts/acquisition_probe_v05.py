"""Bounded public-YouTube acquisition probe; report raw-provider errors privately only.

The public CI artifact intentionally excludes raw HTTP error strings, signed URLs
and possible secret-bearing upstream data. This is not an ASR success test.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from nass_mcp.core import Engine, get_video_id
from nass_mcp.failure_analysis import classify_failure, diagnose_attempts

VIDEO_ID = get_video_id(os.environ.get("NASS_PROBE_VIDEO", "jNQXAC9IVRw"))
AUDIO_CLIENT = os.environ.get("NASS_PROBE_AUDIO_CLIENT", "default")
OUT = Path(os.environ.get("NASS_PROBE_REPORT", "nass-live-acquisition.json"))
ROOT = Path(os.environ.get("NASS_PROBE_DATA", "/tmp/nass-probe"))


def make_report() -> dict:
    return {
        "video_id": VIDEO_ID, "caption": None, "audio": None,
        "audio_client": AUDIO_CLIENT,
        "message": "Network acquisition only; no speech recognition or permanent uptime verified.",
    }


def save(report: dict) -> None:
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if AUDIO_CLIENT not in ("default", "mweb", "web_embedded", "ios"):
        raise SystemExit("Unsupported diagnostic audio client")
    report = make_report()
    engine = Engine(ROOT)
    work = ROOT / "live-probe"
    work.mkdir(parents=True, exist_ok=True)
    save(report)
    attempts = []
    start = time.monotonic()
    try:
        captions = engine.get_captions(VIDEO_ID, "auto", work, attempts)
        report["caption"] = {
            "success": bool(captions), "source": captions[1] if captions else None,
            "segments": len(captions[0]) if captions else 0,
            "diagnosis": diagnose_attempts(attempts),
            "elapsed_seconds": round(time.monotonic() - start, 2),
        }
    except Exception as exc:
        report["caption"] = {
            "success": False, "failure": classify_failure(str(exc))["category"],
            "diagnosis": diagnose_attempts(attempts),
        }
    save(report)
    start = time.monotonic()
    try:
        path = engine.ytdlp_audio(VIDEO_ID, work / "direct-audio", AUDIO_CLIENT)
        duration = engine.check_audio(path)
        report["audio"] = {
            "success": True, "source": "yt-dlp/" + AUDIO_CLIENT,
            "duration_seconds": duration, "size_bytes": path.stat().st_size,
            "elapsed_seconds": round(time.monotonic() - start, 2),
        }
    except Exception as exc:
        report["audio"] = {
            "success": False, "source": "yt-dlp/" + AUDIO_CLIENT,
            "failure": classify_failure(str(exc))["category"],
            "elapsed_seconds": round(time.monotonic() - start, 2),
        }
    report["acquisition_succeeded"] = bool(
        report["caption"].get("success") or report["audio"].get("success")
    )
    report["audio_acquired"] = bool(report["audio"].get("success"))
    save(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["acquisition_succeeded"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
