"""Evaluate actual local ASR against a rights-cleared, reference-backed manifest.

Example:
  NASS_MEDIA_DIR=./media NASS_WHISPER_MODEL=small python scripts/arabic_asr_benchmark.py \
     --manifest ./evaluation/arabic-manifest.jsonl --output ./eval-report.json

Manifest rows: {"id":"clip01","audio":"clip01.wav","reference":"...","reference_quality":"human_verified",
                "source":"original owner","license":"CC BY 4.0","language":"ar"}
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nass_mcp.benchmark import score, aggregate
from nass_mcp.core import Engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("arabic-asr-report.json"))
    parser.add_argument("--max-samples", type=int, default=20)
    parser.add_argument("--policy", choices=["literal", "arabic_basic"], default="arabic_basic")
    args = parser.parse_args()
    if not 1 <= args.max_samples <= 100:
        parser.error("max-samples must be within 1..100")
    report = {"model": os.environ.get("NASS_WHISPER_MODEL", "small"),
              "policy": args.policy, "rows": [],
              "source": "local audio decoding and ASR, not YouTube acquisition",
              "note": "No paid endpoints; user is responsible for source rights and reference quality."}
    engine = Engine()
    with args.manifest.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            if len(report["rows"]) >= args.max_samples:
                break
            if len(line) > 50000:
                raise ValueError("Manifest line exceeds limit")
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("Each manifest line must be a JSON object")
            for field in ("id", "audio", "reference", "license", "source"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError(f"Manifest row missing nonempty field: {field}")
            if item.get("reference_quality") not in ("human_verified", "unverified"):
                raise ValueError("reference_quality must be human_verified or unverified")
            lang = item.get("language", "ar")
            if lang not in ("ar", "en"):
                raise ValueError("This benchmark supports explicit ar and en language hints")
            result = engine.transcribe_file(item["audio"], lang)
            row = {"id": item["id"], "language": lang,
                   "reference_quality": item["reference_quality"],
                   "source": item["source"], "license": item["license"],
                   "ok": bool(result.get("ok")) and result.get("is_audio_asr") is True,
                   "method": result.get("source"), "segments": len(result.get("segments") or [])}
            if row["ok"]:
                prediction = " ".join(seg["text"] for seg in result["segments"])
                row["metrics"] = score(item["reference"], prediction, args.policy)
            else:
                row["failure"] = "No successful local audio ASR; inspect private per-provider logs"
            report["rows"].append(row)
    report["aggregate"] = aggregate(report["rows"])
    report["passed"] = bool(report["rows"]) and all(r["ok"] for r in report["rows"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "count": len(report["rows"]),
                      "aggregate": report["aggregate"], "file": str(args.output)}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
