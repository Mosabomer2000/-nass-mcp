"""Review recommendations around ASR decoder-window seams.

Only human listening can verify if any words were lost or duplicated. This
helper returns bounded excerpts and estimated segment positions, not accuracy.
"""
from __future__ import annotations

import math

from .delivery import load_result
from .longform import plan_windows

MAX_SEAMS_PER_PAGE = 20
MAX_SEGMENTS_PER_SEAM = 8
MAX_SEGMENT_CHARS = 180


def seam_review_page(store, job_id: str, start_seam: int = 0,
                     count: int = 8, context_seconds: float = 5.0,
                     include_text: bool = True) -> dict:
    """Return bounded manual-listening windows based on persisted ASR provenance."""
    if type(start_seam) is not int or start_seam < 0:
        raise ValueError("start_seam must be a non-negative integer")
    if type(count) is not int or not 1 <= count <= MAX_SEAMS_PER_PAGE:
        raise ValueError("count must be in 1..20")
    if not isinstance(context_seconds, (int, float)) or isinstance(context_seconds, bool):
        raise ValueError("Invalid context_seconds")
    context = float(context_seconds)
    if not math.isfinite(context) or not 1 <= context <= 20:
        raise ValueError("context_seconds must be in 1..20")
    if type(include_text) is not bool:
        raise ValueError("include_text must be boolean")
    _, data = load_result(store, job_id)
    recognition = data.get("recognition")
    if not data.get("is_audio_asr") or not isinstance(recognition, dict) or recognition.get("backend") != "faster-whisper":
        return {"ok": False, "job_id": job_id,
                "error": "Decoder-window review requires actual faster-whisper ASR metadata"}
    duration = recognition.get("duration_seconds")
    chunk = recognition.get("configured_chunk_seconds")
    overlap = recognition.get("configured_overlap_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
        return {"ok": False, "job_id": job_id,
                "error": "Recording duration was not saved; reprocess using current Nass"}
    if not isinstance(chunk, int) or chunk < 0 or not isinstance(overlap, (int, float)):
        return {"ok": False, "job_id": job_id, "error": "Window configuration missing"}
    if chunk == 0 or duration <= chunk:
        return {"ok": True, "job_id": job_id, "seam_count": 0, "seams": [],
                "next_seam": None, "note": "One-pass decoding has no chunk seams."}
    windows = plan_windows(float(duration), chunk, float(overlap))
    seams = [w.own_until for w in windows[:-1]]
    if start_seam > len(seams):
        raise ValueError("Seam offset exceeds total number of seams")
    result = []
    audio_segments = data["segments"]
    for index in range(start_seam, min(start_seam+count, len(seams))):
        t = seams[index]
        begin, end = max(0.0, t-context), min(float(duration), t+context)
        nearby = []
        matches = 0
        for segment_index, item in enumerate(audio_segments):
            try:
                seg_start, seg_end = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(seg_start) or not math.isfinite(seg_end):
                continue
            if seg_end < begin or seg_start > end:
                continue
            matches += 1
            if len(nearby) >= MAX_SEGMENTS_PER_SEAM:
                continue
            entry = {"segment_index": segment_index, "start": seg_start, "end": seg_end}
            if include_text:
                entry["text"] = str(item.get("text", ""))[:MAX_SEGMENT_CHARS]
            nearby.append(entry)
        result.append({
            "seam_index": index, "seam_seconds": round(t, 3),
            "listen_from_seconds": round(begin, 3),
            "listen_until_seconds": round(end, 3),
            "segments_near_seam": nearby,
            "nearby_segment_count": matches,
            "segments_truncated": matches > len(nearby),
            "review_required": True,
        })
    next_seam = start_seam+len(result)
    return {"ok": True, "job_id": job_id, "seam_count": len(seams),
            "seams": result,
            "next_seam": next_seam if next_seam < len(seams) else None,
            "accuracy_verified": False,
            "notice": ("Review the source audio on both sides of every seam. "
                       "An empty interval may be legitimate silence; overlap or "
                       "accurate-looking timestamps cannot prove word accuracy.")}
