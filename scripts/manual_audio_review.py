"""Local, human-in-the-loop audit of long Arabic transcript seams.

Examples:
  python scripts/manual_audio_review.py template --result /path/job/result.json \
    --audio /path/original.wav --output /private/annotations.jsonl
  # Open the generated JSONL locally, listen, fill reference_text, then set
  # review_state=human_checked and reviewer_attestation=true for reviewed rows.
  python scripts/manual_audio_review.py score --result /path/job/result.json \
    --audio /path/original.wav --manifest /private/annotations.jsonl \
    --output /private/review-metrics.json

Never upload the manifest, audio or machine transcript to a public artifact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nass_mcp.manual_review import file_digest, review_template, evaluate_reviews


def read_result(path: Path) -> dict:
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid transcription result")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("template", "score"):
        s = sub.add_parser(name)
        s.add_argument("--result", type=Path, required=True)
        s.add_argument("--audio", type=Path, required=True)
        s.add_argument("--output", type=Path, required=True)
        if name == "template":
            s.add_argument("--context", type=float, default=8)
            s.add_argument("--controls", type=int, default=8, help="Deterministic non-seam intervals")
        else:
            s.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    data = read_result(args.result)
    digest = file_digest(args.audio)
    if args.command == "template":
        rows = review_template(data, digest, args.context, control_intervals=args.controls)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False)+"\n")
        print(json.dumps({"status": "pending_human_review", "review_rows": len(rows),
                          "local_manifest": str(args.output),
                          "has_verified_references": False}, ensure_ascii=False))
    else:
        rows = [json.loads(line) for line in args.manifest.read_text("utf-8").splitlines() if line.strip()]
        report = evaluate_reviews(data, rows, digest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps({"scored_rows": report["scored_rows"],
                          "micro_wer_on_attested_excerpts": report["aggregate"]["human_verified_micro_wer"],
                          "local_report": str(args.output),
                          "whole_recording_accuracy_claimed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
