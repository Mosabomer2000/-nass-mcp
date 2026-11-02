"""Export private, exact-audio review clips for human transcription.

The index deliberately excludes both ASR output and human reference text.
Clips remain on the operator's machine; do not upload them to public CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from nass_mcp.manual_review import file_digest, validate_result
from nass_mcp.review_ui import render_review_html
from nass_mcp.media_integrity import require_matching_media

MAX_CLIPS = 200
MAX_CLIP_SECONDS = 180.0


def _duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=duration", "-of",
         "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True, timeout=30)
    output = proc.stdout.strip().splitlines()
    # Some containers do not expose a duration for a stream. Fall back to
    # the format-level duration, never to a guessed value.
    if not output or output[0] in {"N/A", ""}:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True, timeout=30)
        output = proc.stdout.strip().splitlines()
    if not output:
        raise ValueError("Audio duration could not be verified")
    duration = float(output[0])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid physical audio duration")
    return duration


def prepare_intervals(result: dict, rows: list[dict], digest: str,
                      physical_duration: float) -> list[dict]:
    """Validate binding and intervals; never rely on editable reviewer fields."""
    _, job_duration = validate_result(result)
    require_matching_media(result, digest)
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CLIPS:
        raise ValueError("Review manifest must contain 1..200 rows")
    if physical_duration + 0.15 < job_duration:
        raise ValueError("Provided audio is shorter than the ASR job")
    output = []
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Invalid review manifest row")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError("Missing or duplicate review ID")
        seen.add(identifier)
        if row.get("audio_sha256") != digest:
            raise ValueError("Audio SHA256 mismatch: review belongs to another file")
        if row.get("kind") not in ("decoder_seam", "interior_control", "custom"):
            raise ValueError("Invalid review kind")
        start, end = row.get("start_seconds"), row.get("end_seconds")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (start, end)):
            raise ValueError("Invalid review interval coordinates")
        start, end = float(start), float(end)
        if not all(math.isfinite(v) for v in (start, end)):
            raise ValueError("Non-finite review interval")
        if not (0 <= start < end <= job_duration and end <= physical_duration + 0.01):
            raise ValueError("Review interval exceeds recording duration")
        if end - start > MAX_CLIP_SECONDS:
            raise ValueError("Review clip exceeds 180-second safety bound")
        output.append({
            "id": identifier, "kind": row["kind"],
            "start_seconds": start, "end_seconds": end,
            "clip_file": f"clip_{i+1:04d}.wav",
        })
    ordered = sorted(output, key=lambda r: r["start_seconds"])
    if any(left["end_seconds"] > right["start_seconds"] + 0.001
           for left, right in zip(ordered, ordered[1:])):
        raise ValueError("Review intervals overlap")
    return output


def export_review_clips(audio: Path, result: dict, rows: list[dict],
                        output_dir: Path) -> dict:
    """Produce WAV snippets and a text-free index inside a new private folder."""
    audio = Path(audio).resolve(strict=True)
    if not audio.is_file():
        raise ValueError("Audio path must be a file")
    digest = file_digest(audio)
    physical_duration = _duration(audio)
    intervals = prepare_intervals(result, rows, digest, physical_duration)
    dest = Path(output_dir).resolve()
    if dest.exists():
        raise FileExistsError("Output directory already exists; use a new private directory")
    dest.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(dest, 0o700)
    try:
        for item in intervals:
            clip = dest / item["clip_file"]
            command = [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-accurate_seek", "-ss", f'{item["start_seconds"]:.3f}',
                "-i", str(audio), "-t",
                f'{item["end_seconds"] - item["start_seconds"]:.3f}',
                "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", "-n", str(clip),
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=150)
            if not clip.is_file() or clip.stat().st_size < 50:
                raise ValueError("FFmpeg did not create a valid audio snippet")
            os.chmod(clip, 0o600)
        index = {
            "status": "awaiting_human_review",
            "audio_sha256": digest,
            "job_audio_seconds": result["recognition"]["duration_seconds"],
            "clip_count": len(intervals),
            "clips": intervals,
            "machine_transcript_included": False,
            "reference_transcript_included": False,
            "whole_recording_accuracy_verified": False,
            "instruction": "Listen locally, correct the ORIGINAL JSONL manifest, and run manual_audio_review.py score.",
        }
        index_file = dest / "index.json"
        index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")
        os.chmod(index_file, 0o600)
        page = dest / "review.html"
        page.write_text(render_review_html(intervals, digest), "utf-8")
        os.chmod(page, 0o600)
    except Exception:
        shutil.rmtree(dest)
        raise
    return {
        "status": "private_audio_clips_prepared",
        "clip_count": len(intervals),
        "local_output_directory": str(dest),
        "review_page": str(dest / "review.html"),
        "human_review_completed": False,
        "transcript_text_exported": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.result.read_text("utf-8"))
    rows = [json.loads(line) for line in args.manifest.read_text("utf-8").splitlines()
            if line.strip()]
    output = export_review_clips(args.audio, data, rows, args.output_dir)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
