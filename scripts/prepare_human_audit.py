"""Create a complete PRIVATE listening-review pack for a finished Nass ASR job.

This deliberately cannot label any machine words as human-verified.
No API, uploads, network traffic, or automatic reference transcription.
Requires the original EXACT bytes used for ASR and a source-bound result.json.

Examples:
  python -m scripts.prepare_human_audit \
    --audio "$NASS_MEDIA_DIR/lecture.flac" \
    --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
    --output-dir "$HOME/nass-private-review-001"
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

from nass_mcp.manual_review import file_digest, review_template
from scripts.export_review_clips import export_review_clips


def prepare_audit(audio: Path, result: dict, output_dir: Path, *,
                  context_seconds: float = 8.0,
                  control_intervals: int = 8,
                  max_seams: int = 40) -> dict:
    """Make clips + review.html + checkpoint JSONL, all locally.

    The clip exporter verifies that the audio digest matches the SHA-256
    recorded by the recognition engine before any directory is created.
    """
    digest = file_digest(audio)
    rows = review_template(result, digest, context_seconds=context_seconds,
                           control_intervals=control_intervals, limit=max_seams)
    if not rows:
        raise ValueError(
            "No decoder seams or interior controls selected; cannot create an empty review pack"
        )
    folder = Path(output_dir).resolve()
    report = export_review_clips(audio, result, rows, folder)
    try:
        manifest = folder / "annotations-pending.jsonl"
        with manifest.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.chmod(manifest, 0o600)
        report.update({
            "pending_manifest": str(manifest),
            "human_verified_rows": 0,
            "full_recording_wer": None,
            "full_recording_cer": None,
            "review_required": True,
        })
    except Exception:
        # This directory was created by this call, never an existing user path.
        shutil.rmtree(folder)
        raise
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--context", type=float, default=8.0)
    parser.add_argument("--controls", type=int, default=8)
    parser.add_argument("--max-seams", type=int, default=40)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    info = prepare_audit(args.audio, result, args.output_dir,
                         context_seconds=args.context,
                         control_intervals=args.controls,
                         max_seams=args.max_seams)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
