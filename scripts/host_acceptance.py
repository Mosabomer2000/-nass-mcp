"""Operator-controlled host acceptance check, without publishing private transcripts.

Examples:
  python scripts/host_acceptance.py --local-file mylecture.wav --language ar
  python scripts/host_acceptance.py --youtube 'https://youtu.be/VIDEOID' --language ar
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path

from nass_mcp.host_acceptance import run_acceptance


def main():
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--youtube", help="Public video to acquire and recognize from actual audio")
    group.add_argument("--local-file", help="Existing audio in NASS_MEDIA_DIR")
    p.add_argument("--language", default="ar")
    p.add_argument("--max-wait", type=int, default=1800)
    p.add_argument("--output", type=Path, default=Path("nass-host-acceptance.json"))
    args = p.parse_args()
    try:
        result = asyncio.run(run_acceptance(
            youtube=args.youtube, local_file=args.local_file,
            language=args.language, max_wait_seconds=args.max_wait))
    except Exception as exc:
        # Never print potentially sensitive upstream messages or user media text.
        result = {"passed": False, "failure_class": type(exc).__name__,
                  "note": "Inspect private worker diagnostics; raw errors are not published."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("passed"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
