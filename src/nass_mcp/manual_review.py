"""Human-verified excerpt evaluation: avoid claiming whole-lecture accuracy.

This module operates on LOCAL audio/result files only. It never uploads either
file, and it does not infer human verification from automatically generated text.
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from .benchmark import score, aggregate
from .longform import plan_windows


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_result(result: dict) -> tuple[list[dict], float]:
    if not isinstance(result, dict) or result.get("is_audio_asr") is not True:
        raise ValueError("Result must be actual audio-ASR output")
    if not str(result.get("source", "")).startswith("asr:"):
        raise ValueError("Unknown transcription source")
    metadata = result.get("recognition") or {}
    duration = metadata.get("duration_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise ValueError("Missing measured recording duration")
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid recording duration")
    segments = result.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Invalid ASR segments")
    for item in segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("Invalid ASR segment")
        a, b = float(item["start"]), float(item["end"])
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a <= b <= duration+0.1):
            raise ValueError("Invalid ASR segment timestamps")
    return segments, duration


def review_template(result: dict, audio_sha256: str,
                    context_seconds: float = 8.0, limit: int = 40,
                    control_intervals: int = 0) -> list[dict]:
    """Prepare a LOCAL, unreviewed annotation form for actual seam intervals."""
    segments, duration = validate_result(result)
    if not isinstance(audio_sha256, str) or len(audio_sha256) != 64:
        raise ValueError("Missing input audio SHA256")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid review count")
    if not math.isfinite(context_seconds) or not 1 <= context_seconds <= 30:
        raise ValueError("Invalid context")
    if type(control_intervals) is not int or not 0 <= control_intervals <= 40:
        raise ValueError("control_intervals must be 0..40")
    settings = result.get("recognition") or {}
    chunk = settings.get("configured_chunk_seconds")
    overlap = settings.get("configured_overlap_seconds")
    if not isinstance(chunk, int) or chunk <= 0:
        raise ValueError("A chunked Whisper job is required for seam-template generation")
    windows = plan_windows(duration, chunk, overlap)
    raw_seams = [window.own_until for window in windows[:-1]]
    rows = []
    for index, t in enumerate(raw_seams[:limit]):
        first, last = max(0.0, t-context_seconds), min(duration, t+context_seconds)
        touching = [s for s in segments
                    if float(s["end"]) >= first and float(s["start"]) <= last]
        # Expand to entire model utterance boundaries, so the human audio
        # reference can be compared to complete machine segments.
        if touching:
            first = max(0.0, min(first, *(float(s["start"]) for s in touching)))
            last = min(duration, max(last, *(float(s["end"]) for s in touching)))
        rows.append({
            "id": f"seam-{index:04d}", "kind": "decoder_seam",
            "seam_seconds": round(t, 3),
            "start_seconds": round(first, 3), "end_seconds": round(last, 3),
            "audio_sha256": audio_sha256,
            "reference_text": "",
            "review_state": "pending",
            "reviewer_attestation": False,
            "note": "Listen to the actual audio, fill in precise words and mark human_checked.",
        })
    # Choose deterministic *non-seam* controls to compare accuracy at
    # ordinary places vs at decoder boundaries. These are review invitations,
    # not human attestations or ground truth.
    rng = random.Random(int(hashlib.sha256(audio_sha256.encode("ascii")).hexdigest(), 16))
    attempts = 0
    while sum(row["kind"] == "interior_control" for row in rows) < control_intervals and attempts < 400:
        attempts += 1
        center = rng.uniform(context_seconds, duration-context_seconds) if duration > 2*context_seconds else duration/2
        start = max(0.0, center-context_seconds)
        end = min(duration, center+context_seconds)
        if any(abs(center-t) < 2*context_seconds+2 for t in raw_seams):
            continue
        touching = [seg for seg in segments
                    if float(seg["end"]) >= start and float(seg["start"]) <= end]
        if not touching:
            continue
        start = max(0.0, min(start, *(float(seg["start"]) for seg in touching)))
        end = min(duration, max(end, *(float(seg["end"]) for seg in touching)))
        # Samples must be disjoint after expanding to full machine segments.
        if any(start < row["end_seconds"]-0.001 and end > row["start_seconds"]+0.001
               for row in rows):
            continue
        number = sum(row["kind"] == "interior_control" for row in rows)
        rows.append({
            "id": f"control-{number:04d}", "kind": "interior_control",
            "start_seconds": round(start, 3), "end_seconds": round(end, 3),
            "audio_sha256": audio_sha256, "reference_text": "",
            "review_state": "pending", "reviewer_attestation": False,
            "note": "Listen and transcribe exactly; this is a non-seam baseline.",
        })
    return rows


def evaluate_reviews(result: dict, rows: list[dict], audio_sha256: str) -> dict:
    """Score human-attested LOCAL excerpts without silently scoring partial ASR text.

    Overlap or a segment crossing the annotation interval invalidates a
    WER/CER comparison because the model did not emit word-level alignment.
    """
    segments, duration = validate_result(result)
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("Invalid review manifest")
    if not isinstance(audio_sha256, str) or len(audio_sha256) != 64:
        raise ValueError("Invalid audio SHA256")
    seen = set()
    intervals = []
    scored = []
    rejected = []
    for i, row in enumerate(rows):
        item_id = str(row.get("id", "")) if isinstance(row, dict) else ""
        if not item_id or item_id in seen:
            raise ValueError("Review rows must have unique nonempty identifiers")
        seen.add(item_id)
        try:
            start, end = float(row["start_seconds"]), float(row["end_seconds"])
        except (KeyError, ValueError, TypeError):
            raise ValueError("Review interval is missing or invalid") from None
        if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end <= duration:
            raise ValueError("Review interval outside the source recording")
        intervals.append((start, end, item_id))
        if row.get("audio_sha256") != audio_sha256:
            raise ValueError("Review references a different audio file")
        if row.get("review_state") != "human_checked" or row.get("reviewer_attestation") is not True:
            rejected.append({"id": item_id, "reason": "not_human_attested"})
            continue
        reference = row.get("reference_text")
        if not isinstance(reference, str) or not reference.strip():
            rejected.append({"id": item_id, "reason": "reference_missing"})
            continue
        included = []
        ambiguous = False
        for segment in segments:
            a, b = float(segment["start"]), float(segment["end"])
            if b <= start or a >= end:
                continue
            if a < start - 0.001 or b > end + 0.001:
                ambiguous = True
                break
            included.append(segment["text"])
        if ambiguous:
            rejected.append({"id": item_id, "reason": "segment_crosses_review_boundary"})
            continue
        prediction = " ".join(included)
        try:
            metrics = score(reference, prediction, "arabic_basic")
        except ValueError:
            rejected.append({"id": item_id, "reason": "reference_not_comparable"})
            continue
        kind = row.get("kind", "custom")
        if kind not in ("decoder_seam", "interior_control", "custom"):
            raise ValueError("Unsupported audit group")
        scored.append({"id": item_id, "kind": kind, "ok": True,
                       "reference_quality": "human_verified", "metrics": metrics})
    # Require non-overlapping attested intervals; otherwise a word can count
    # several times and make the micro-average statistically misleading.
    sorted_intervals = sorted(intervals)
    for left, right in zip(sorted_intervals, sorted_intervals[1:]):
        if left[1] > right[0]+0.001:
            raise ValueError("Review intervals overlap; revise annotation boundaries")
    total = aggregate(scored)
    per_kind = {
        kind: aggregate([row for row in scored if row["kind"] == kind])
        for kind in ("decoder_seam", "interior_control", "custom")
    }
    return {
        "source": "human-attested local audio excerpts",
        "metrics_by_review_kind": per_kind,
        "review_rows": len(rows), "scored_rows": len(scored),
        "excluded_rows": rejected,
        "aggregate": total,
        "full_recording_wer": None,
        "audio_sha256_verified_by_caller": True,
        "warning": ("Only self-attested, well-aligned excerpts are scored. "
                    "This is neither whole-lecture WER nor independent validation "
                    "of the reviewer's work. Actual source audio must be checked."),
    }
