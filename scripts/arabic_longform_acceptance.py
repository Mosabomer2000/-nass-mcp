"""Real multi-window Arabic Whisper test from SHA-verified open dataset clips.

This concatenated speech is a technical boundary fixture, not a natural lecture.
No audio files or words are included in the public artifact.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess

from nass_mcp.benchmark import score
from nass_mcp.core import Engine
from nass_mcp.host_acceptance import run_acceptance
from nass_mcp.longform import plan_windows
from nass_mcp.server import jobs


async def main():
    manifest = Path("nass-arabic-eval.jsonl")
    rows = [json.loads(line) for line in manifest.read_text("utf-8").splitlines() if line.strip()]
    if len(rows) != 10:
        raise RuntimeError("Expected ten checksum-verified Arabic clips")
    media = Path(os.environ["NASS_MEDIA_DIR"])
    names = [media / row["audio"] for row in rows]
    for path in names:
        if not path.is_file() or not path.is_relative_to(media):
            raise RuntimeError("Missing approved dataset audio clip")
    destination = media / "arabic-fleurs-concatenated.wav"
    audio_inputs = []
    for path in names:
        audio_inputs.extend(["-i", str(path)])
    pads = "".join("[" + str(i) + ":a:0]" for i in range(len(names)))
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *audio_inputs,
         "-filter_complex", pads + f"concat=n={len(names)}:v=0:a=1[a]",
         "-map", "[a]", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
         str(destination)],
        timeout=120, check=True, capture_output=True,
    )
    engine = Engine()
    duration = engine.check_audio(destination)
    chunk = int(os.environ["NASS_ASR_CHUNK_SECONDS"])
    overlap = float(os.environ["NASS_ASR_OVERLAP_SECONDS"])
    windows = plan_windows(duration, chunk, overlap)
    if len(windows) < 3:
        raise RuntimeError("Arabic sample must use at least three real decoder windows")
    output = await run_acceptance(local_file=destination.name, language="ar",
                                  max_wait_seconds=600)
    output.update({
        "test_kind": "ten synthetic-concatenated, verified FLEURS Arabic clips",
        "model": os.environ.get("NASS_WHISPER_MODEL"),
        "source_clip_count": len(names),
        "duration_seconds": round(duration, 2),
        "planned_windows": len(windows),
        "human_verified_references": 0,
        "reference_rights": "CC BY-SA 4.0",
        "audio_rights": "CC BY 4.0",
        "spoken_words_logged": False,
        "reference_benchmark_warning": "Published prompts are not human-audited verbatim audio transcriptions.",
    })
    if output.get("mcp_job_completed"):
        result = json.loads((jobs.base / output["job_id"] / "result.json").read_text("utf-8"))
        segments = result.get("segments", [])
        text = " ".join(str(item.get("text", "")) for item in segments)
        reference = " ".join(row["reference"] for row in rows)
        output["metrics"] = score(reference, text, "arabic_basic")
        output["timestamp_monotonic"] = all(
            segments[i]["start"] <= segments[i+1]["start"]
            for i in range(len(segments)-1))
        output["speech_near_end"] = bool(segments and segments[-1]["end"] >= duration * 0.6)
        output["passed"] = bool(output["passed"] and output["timestamp_monotonic"]
                                and output["speech_near_end"] and len(segments) >= len(windows))
    path = Path("nass-arabic-longform-report.json")
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output.get("passed"):
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
