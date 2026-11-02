"""Host-side, privacy-preserving Nass acceptance probe through actual MCP tools."""
from __future__ import annotations

import asyncio
import json
import re
import time

from mcp import Client

from .core import get_video_id
from .server import mcp


def unwrap(result) -> dict:
    """Read result dictionaries from MCP SDK 2.x's structured or text content."""
    candidates = [getattr(result, "structured_content", None)]
    for item in getattr(result, "content", []):
        raw = getattr(item, "text", None)
        if not raw:
            continue
        try:
            candidates.append(json.loads(raw))
        except (TypeError, ValueError):
            pass
    def find(node, depth=0):
        if depth > 5 or not isinstance(node, dict):
            return None
        if any(key in node for key in ("job_id", "state", "total_segments",
                                        "anomaly_count", "cancelled")):
            return node
        for key in ("result", "data", "value"):
            found = find(node.get(key), depth + 1)
            if found is not None:
                return found
        return None
    for item in candidates:
        found = find(item)
        if found is not None:
            return found
    raise RuntimeError("MCP tool did not return a valid structured result")


async def run_acceptance(*, youtube: str | None = None, local_file: str | None = None,
                         language: str = "ar", max_wait_seconds: int = 1800) -> dict:
    """Actually exercise queue, media acquisition (if YouTube), ASR and MCP paging.

    The result intentionally includes NO transcript text or raw provider errors.
    This test cannot independently measure transcript accuracy.
    """
    if (bool(youtube) + bool(local_file)) != 1:
        raise ValueError("Specify exactly one of YouTube URL or local file name")
    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*|auto", language):
        raise ValueError("Invalid language")
    if not 30 <= max_wait_seconds <= 14400:
        raise ValueError("Invalid acceptance timeout")
    input_kind = "youtube" if youtube else "local_file"
    if youtube:
        get_video_id(youtube)
        tool, kwargs = "nass_start_transcription", {
            "video_url": youtube, "language": language, "mode": "audio"}
    else:
        tool, kwargs = "nass_start_local_file", {"filename": local_file,
                                                  "language": language}
    output = {
        "passed": False, "input_kind": input_kind, "language": language,
        "audio_acquired": False, "actual_audio_asr": False, "mcp_job_completed": False,
        "mcp_delivery": False, "mcp_structural_qa": False,
        "accuracy_verified": False,
        "notice": ("Source-access success and a text result do not establish accuracy. "
                   "Listen and verify quotations against the recording."),
    }
    started = time.monotonic()
    async with Client(mcp, raise_exceptions=True) as client:
        submission = unwrap(await client.call_tool(tool, kwargs))
        jobid = submission.get("job_id")
        if not isinstance(jobid, str) or not re.fullmatch(r"[0-9a-f]{32}", jobid):
            output["failure_class"] = "mcp_submission_failure"
            return output
        output["job_id"] = jobid
        status = {}
        while time.monotonic() - started < max_wait_seconds:
            status = unwrap(await client.call_tool("nass_job_status", {"job_id": jobid}))
            if status.get("state") in ("completed", "failed", "cancelled", "interrupted"):
                break
            await asyncio.sleep(1)
        else:
            output["failure_class"] = "job_timeout"
            return output
        output["state"] = status.get("state")
        output["elapsed_seconds"] = round(time.monotonic() - started, 2)
        if status.get("state") != "completed":
            diagnostics = unwrap(await client.call_tool("nass_job_diagnostics", {"job_id": jobid}))
            output["failure_categories"] = diagnostics.get("categories", {})
            output["failure_class"] = "job_failed_or_interrupted"
            return output
        output["mcp_job_completed"] = True
        transcript = unwrap(await client.call_tool("nass_get_transcript",
                    {"job_id": jobid, "start_segment": 0, "count": 20}))
        output["asr_source"] = transcript.get("source")
        output["audio_source"] = transcript.get("audio_source")
        output["segment_count"] = transcript.get("total_segments")
        output["actual_audio_asr"] = (bool(transcript.get("is_audio_asr")) and
                                     str(transcript.get("source", "")).startswith("asr:") and
                                     (transcript.get("total_segments") or 0) > 0)
        output["audio_acquired"] = bool(transcript.get("audio_source"))
        if not output["actual_audio_asr"]:
            output["failure_class"] = "no_real_asr_output"
            return output
        page = unwrap(await client.call_tool("nass_transcript_page",
                    {"job_id": jobid, "output_format": "md", "max_chars": 12000}))
        output["mcp_delivery"] = (page.get("ok") is True and
                                  bool(page.get("content")) and
                                  page.get("total_chars", 0) > 0)
        output["total_transcript_characters"] = page.get("total_chars")
        report = unwrap(await client.call_tool("nass_quality_report", {"job_id": jobid}))
        output["mcp_structural_qa"] = (report.get("ok") is True and
                                      report.get("accuracy_score") is None and
                                      report.get("segment_count") == output["segment_count"])
        output["structural_anomaly_count"] = report.get("anomaly_count")
        output["passed"] = all(output[key] for key in
                               ("audio_acquired", "actual_audio_asr",
                                "mcp_job_completed", "mcp_delivery",
                                "mcp_structural_qa"))
        return output
