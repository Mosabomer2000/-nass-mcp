"""Portable transcript delivery, independent verification and structural quality checks.

Export payloads are paginated and provenance-labelled; confidence is not invented.
"""
from __future__ import annotations

import json
import math
from .core import JobStore, canonical_url, seconds_to_srt

FORMATS = {"txt", "srt", "vtt", "md", "json"}
MAX_CHARS = 16000


def load_result(store: JobStore, job_id: str) -> tuple[dict, dict]:
    status = store.get_status(job_id)  # validates UUID
    if status["state"] != "completed":
        raise ValueError("Job is not completed")
    path = store.base / job_id / "result.json"
    if not path.is_file():
        raise ValueError("Result file not found")
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("segments"), list):
        raise ValueError("No successful timestamped transcript")
    return status, data


def render(result: dict, fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError("Unsupported export format")
    segments = result.get("segments", [])
    if fmt == "json":
        # Include transcript data but do not repeat raw third-party errors or signed URLs.
        keys = ("video_id", "language", "source", "audio_source", "is_audio_asr", "segments", "verification")
        return json.dumps({k: result.get(k) for k in keys}, ensure_ascii=False, indent=2)
    if fmt == "txt":
        return "\n".join(str(s["text"]) for s in segments) + ("\n" if segments else "")
    if fmt in ("srt", "vtt"):
        marker = "." if fmt == "vtt" else ","
        items = []
        for n, s in enumerate(segments, 1):
            first = seconds_to_srt(float(s["start"])).replace(",", marker)
            last = seconds_to_srt(float(s["end"])).replace(",", marker)
            items.append(("" if fmt == "vtt" else str(n) + "\n") +
                         first + " --> " + last + "\n" + str(s["text"]))
        return ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n\n".join(items) + ("\n" if items else "")
    vid = result.get("video_id")
    try:
        url = canonical_url(vid) if vid != "local-file" else None
    except (ValueError, TypeError):
        url = None
    head = ["# Transcription", "", "Source: " + str(result.get("source")),
            "Language: " + str(result.get("language")),
            "Actual audio ASR: " + str(bool(result.get("is_audio_asr")))]
    if url:
        head.append("Video: " + url)
    head.extend(["", "Machine text may be inaccurate; verify quotations against the source audio.", ""])
    for s in segments:
        t = max(0, int(float(s["start"])))
        stamp = f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"
        if url:
            stamp = f"[{stamp}]({url}&t={t}s)"
        head.extend([f"**{stamp}**  {s['text']}", ""])
    return "\n".join(head).rstrip() + "\n"


def transcript_page(store: JobStore, job_id: str, output_format: str = "md",
                    offset: int = 0, max_chars: int = 12000) -> dict:
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= MAX_CHARS:
        raise ValueError("Invalid pagination bounds")
    status, result = load_result(store, job_id)
    content = render(result, output_format)
    if offset > len(content):
        raise ValueError("Offset exceeds transcript length")
    end = min(len(content), offset + max_chars)
    return {"ok": True, "job_id": job_id, "format": output_format, "source": result.get("source"),
            "is_audio_asr": bool(result.get("is_audio_asr")),
            "completed_at": status.get("finished_at"), "offset": offset,
            "next_offset": end if end < len(content) else None,
            "total_chars": len(content), "content": content[offset:end],
            "warning": "Do not treat generated words or approximate timestamps as verified quotations."}


def verification_page(store: JobStore, job_id: str, track: str = "captions",
                      start_segment: int = 0, count: int = 60) -> dict:
    if track not in ("captions", "audio") or type(start_segment) is not int or start_segment < 0 or type(count) is not int or not 1 <= count <= 100:
        raise ValueError("Invalid verification track or bounds")
    _, result = load_result(store, job_id)
    if track == "audio":
        if not result.get("is_audio_asr"):
            return {"ok": False, "error": "No audio-ASR track in this job"}
        items = result["segments"]
        source = result.get("source")
    else:
        verification = result.get("verification") or {}
        items = verification.get("captions_segments")
        source = verification.get("captions_source")
        if not isinstance(items, list):
            return {"ok": False, "error": "No independent caption track in this job"}
    selected = items[start_segment:start_segment + count]
    end = start_segment + len(selected)
    return {"ok": True, "job_id": job_id, "track": track, "source": source,
            "total_segments": len(items), "segments": selected,
            "next_segment": end if end < len(items) else None,
            "warning": "Independent tracks have not been reconciled or human-verified."}


def quality_report(store: JobStore, job_id: str) -> dict:
    """Structural anomaly count only. These are NOT WER or confidence scores."""
    _, result = load_result(store, job_id)
    segments, issues = result["segments"], []
    anomaly_count, previous_end, previous_start, previous_text, repeats = 0, -1.0, -1.0, None, 0
    total_chars, maximum_end = 0, 0.0

    def add(index: int, code: str, **details) -> None:
        nonlocal anomaly_count
        anomaly_count += 1
        if len(issues) < 100:
            issues.append({"segment": index, "type": code, **details})

    for i, seg in enumerate(segments):
        try:
            start, end = float(seg["start"]), float(seg["end"])
            body = str(seg["text"]).strip()
        except (KeyError, TypeError, ValueError):
            add(i, "invalid_segment")
            continue
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            add(i, "invalid_time_range")
            continue
        if start + 0.01 < previous_start:
            add(i, "out_of_order_timestamp")
        if previous_end >= 0 and start + 0.5 < previous_end:
            add(i, "overlapping_segments")
        if previous_end >= 0 and start - previous_end >= 120:
            add(i, "long_untranscribed_gap", seconds=round(start - previous_end, 1))
        if not body:
            add(i, "empty_segment")
        repeats = repeats + 1 if body and body == previous_text else 0
        if repeats == 3:
            add(i, "four_identical_consecutive_segments")
        previous_text, previous_start, previous_end = body, start, end
        total_chars += len(body)
        maximum_end = max(maximum_end, end)
    if not segments:
        add(-1, "no_segments")
    return {"ok": True, "job_id": job_id, "source": result.get("source"),
            "is_audio_asr": bool(result.get("is_audio_asr")),
            "segment_count": len(segments), "characters": total_chars,
            "timeline_end_seconds": round(maximum_end, 3), "anomalies": issues,
            "anomaly_count": anomaly_count, "anomalies_truncated": anomaly_count > len(issues),
            "accuracy_score": None, "note": "No audio-grounded accuracy measurement or WER was performed."}
