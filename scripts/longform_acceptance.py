"""Actual multi-window Whisper/MCP acceptance using repeated public-domain speech.

The repeated recording exercises chunk decoding and timestamps, not Arabic
accuracy. No copyrighted user-provided material is redistributed or logged.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from nass_mcp.core import Engine
from nass_mcp.host_acceptance import run_acceptance
from nass_mcp.longform import plan_windows
from nass_mcp.seam_review import seam_review_page
from nass_mcp.server import jobs


async def main():
    media = Path(os.environ["NASS_MEDIA_DIR"])
    clip = media / "jfk-repeated.wav"
    seconds = int(os.environ.get("NASS_ASR_CHUNK_SECONDS", "20"))
    overlap = float(os.environ.get("NASS_ASR_OVERLAP_SECONDS", "4"))
    duration = Engine().check_audio(clip)
    windows = plan_windows(duration, seconds, overlap)
    if len(windows) < 3:
        raise RuntimeError("Test audio must require at least three ASR windows")
    report = await run_acceptance(local_file=clip.name, language="en", max_wait_seconds=450)
    report["planned_windows"] = len(windows)
    report["duration_seconds"] = round(duration, 2)
    report["window_size_seconds"] = seconds
    report["overlap_seconds"] = overlap
    report["content_logged"] = False
    if report.get("mcp_job_completed"):
        path = jobs.base / report["job_id"] / "result.json"
        data = json.loads(path.read_text("utf-8"))
        segments = data.get("segments", [])
        seam_report = seam_review_page(jobs, report["job_id"], count=20,
                                       include_text=False)
        report["seam_review_available"] = seam_report.get("ok") is True
        report["seams_requiring_listening"] = seam_report.get("seam_count")
        report["seam_review_contains_spoken_text"] = False
        report["seam_count_matches_windows"] = (
            seam_report.get("seam_count") == len(windows)-1)
        report["recognized_segment_count"] = len(segments)
        report["last_segment_end"] = segments[-1]["end"] if segments else None
        report["timestamp_monotonic"] = all(
            segments[i]["start"] <= segments[i+1]["start"]
            for i in range(len(segments)-1))
        report["speech_recognized_near_end"] = bool(segments and
            segments[-1]["end"] >= duration * 0.6)
        report["passed"] = bool(report["passed"] and
            report["timestamp_monotonic"] and
            report["seam_review_available"] and report["seam_count_matches_windows"] and
            report["speech_recognized_near_end"] and
            report["recognized_segment_count"] >= len(windows))
    path = Path(os.environ.get("NASS_LONGFORM_REPORT", "nass-longform-asr.json"))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
