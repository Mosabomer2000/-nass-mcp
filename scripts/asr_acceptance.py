"""Real, deterministic-ish ASR acceptance test through the Nass MCP SDK.

Input must be a separately fetched, SHA-verified public-domain JFK speech clip.
No mocks, paid APIs, YouTube cookies, or user media are involved.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from mcp import Client
from nass_mcp.server import mcp

MEDIA = Path(os.environ["NASS_MEDIA_DIR"])
REPORT = Path(os.environ.get("NASS_ASR_REPORT", "nass-asr-acceptance.json"))
EXPECTED = "and so my fellow americans ask not what your country can do for you ask what you can do for your country"
FILENAME = "jfk.flac"


def unwrap(data):
    """Handle structured MCP tool returns without relying on a presentation format."""
    candidates = [getattr(data, "structured_content", None)]
    for block in getattr(data, "content", []):
        value = getattr(block, "text", None)
        if value:
            try:
                candidates.append(json.loads(value))
            except (TypeError, ValueError):
                pass
    def find(value, depth=0):
        if depth > 4 or not isinstance(value, dict):
            return None
        if any(key in value for key in ("job_id", "state", "total_segments", "quality_score", "anomaly_count")):
            return value
        for key in ("result", "data", "value"):
            match = find(value.get(key), depth + 1)
            if match is not None:
                return match
        return None
    for candidate in candidates:
        found = find(candidate)
        if found is not None:
            return found
    raise RuntimeError("MCP returned no structured tool payload")


def normalize(text):
    return re.sub(r"[^a-z0-9 ]+", " ", text.casefold()).split()


def wer(reference, hypothesis):
    a, b = normalize(reference), normalize(hypothesis)
    costs = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        next_costs = [i]
        for j, predicted in enumerate(b, 1):
            next_costs.append(min(
                next_costs[-1] + 1, costs[j] + 1,
                costs[j - 1] + (word != predicted)))
        costs = next_costs
    return round(costs[-1] / max(1, len(a)), 4)


def save(report):
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def run():
    report = {
        "fixture": "openai/whisper tests/jfk.flac",
        "fixture_git_blob": "e44b7c13897eae7f78beb220c61fe77429a3961d",
        "model": os.environ.get("NASS_WHISPER_MODEL"),
        "backend": "faster-whisper",
        "actual_audio_decoded": False,
        "actual_asr_executed": False,
        "mcp_job_completed": False,
        "mcp_paging_passed": False,
        "recognized_key_phrases": False,
        "word_error_rate": None,
        "note": "This is an English ASR smoke test, not an Arabic benchmark or proof of YouTube access.",
    }
    try:
        audio = MEDIA / FILENAME
        if not audio.is_file() or audio.stat().st_size < 20000:
            raise RuntimeError("Fixture missing or implausibly small")
        async with Client(mcp, raise_exceptions=True) as client:
            result = unwrap(await client.call_tool(
                "nass_start_local_file", {"filename": FILENAME, "language": "en"}))
            jobid = result.get("job_id")
            if not isinstance(jobid, str) or len(jobid) != 32:
                raise RuntimeError("MCP did not return a valid job id")
            report["job_accepted"] = True
            save(report)
            deadline = time.monotonic() + 240
            state = None
            while time.monotonic() < deadline:
                status = unwrap(await client.call_tool("nass_job_status", {"job_id": jobid}))
                state = status.get("state")
                if state in ("completed", "failed", "interrupted"):
                    break
                await asyncio.sleep(2)
            if state != "completed":
                report["job_state"] = state
                raise RuntimeError("Real ASR job did not complete")
            report["mcp_job_completed"] = True
            first = unwrap(await client.call_tool(
                "nass_get_transcript", {"job_id": jobid, "start_segment": 0, "count": 50}))
            report["actual_asr_executed"] = bool(first.get("is_audio_asr")) and str(first.get("source", "")).startswith("asr:faster-whisper")
            report["actual_audio_decoded"] = bool(first.get("audio_source") == "authorized-local-file")
            segments = first.get("segments") or []
            transcript = " ".join(str(s.get("text", "")) for s in segments).strip()
            if not transcript:
                raise RuntimeError("No text recognized")
            report["transcript"] = transcript
            report["segment_count"] = first.get("total_segments")
            report["word_error_rate"] = wer(EXPECTED, transcript)
            nt = normalize(transcript)
            line = " ".join(nt)
            report["recognized_key_phrases"] = ("fellow americans" in line and "country" in nt)
            export = unwrap(await client.call_tool(
                "nass_transcript_page", {"job_id": jobid, "output_format": "md", "max_chars": 12000}))
            report["mcp_paging_passed"] = export.get("ok") is True and "fellow" in str(export.get("content", "")).lower()
            qa = unwrap(await client.call_tool("nass_quality_report", {"job_id": jobid}))
            report["quality_report_present"] = qa.get("ok") is True and qa.get("accuracy_score") is None
            if not all(report[k] for k in ("actual_audio_decoded", "actual_asr_executed",
                                            "mcp_job_completed", "mcp_paging_passed",
                                            "recognized_key_phrases", "quality_report_present")):
                raise RuntimeError("One or more real ASR acceptance gates failed")
            report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["failure_type"] = type(exc).__name__
        report["failure_description"] = str(exc)[:200]
        raise
    finally:
        save(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
