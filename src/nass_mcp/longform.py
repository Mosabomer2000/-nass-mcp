"""Pure window planning and timestamp merging for bounded-memory long-form ASR.

Boundary timestamps are *hypothesis timing*, not proof of word-level alignment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    own_from: float
    own_until: float


def plan_windows(duration: float, seconds: float = 480, overlap: float = 4) -> list[Window]:
    """Plan overlapping decoder windows, with disjoint midpoint ownership.

    No synthesized silence, transcript or timestamps are introduced. Each window
    has enough preceding/succeeding audio to reduce boundary clipping.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid audio duration")
    if not math.isfinite(seconds) or seconds < 4 or seconds > 1800:
        raise ValueError("Chunk length must be within 4..1800 seconds")
    if not math.isfinite(overlap) or overlap < 0 or overlap >= seconds / 2:
        raise ValueError("Overlap must be nonnegative and smaller than half the chunk")
    if duration <= seconds:
        return [Window(0.0, duration, 0.0, duration)]
    spans = []
    cursor = 0.0
    while cursor < duration:
        end = min(duration, cursor + seconds)
        spans.append((round(cursor, 3), round(end, 3)))
        if end >= duration:
            break
        cursor = end - overlap
        if len(spans) > 10000:
            raise ValueError("Excessive ASR chunk count")
    windows = []
    for index, (start, end) in enumerate(spans):
        lower = 0.0 if index == 0 else (spans[index-1][1] + start) / 2
        upper = duration if index == len(spans)-1 else (end + spans[index+1][0]) / 2
        windows.append(Window(start, end, lower, upper))
    return windows


def combine_segments(windows: list[Window], hypotheses: list[list[dict]],
                     duration: float) -> list[dict]:
    """Offset chunk-relative segments, retaining exactly one owner per midpoint.

    Do not silently treat a missing window as successful. The worker fails the
    entire result when the number of ASR window outputs is inconsistent.
    """
    if len(windows) != len(hypotheses) or not windows:
        raise ValueError("All ASR window results must be available")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid duration")
    result = []
    for window, items in zip(windows, hypotheses):
        for item in items:
            start = float(item["start"]) + window.start
            end = float(item["end"]) + window.start
            content = str(item.get("text", "")).strip()
            if not all(math.isfinite(t) for t in (start, end)) or not content:
                continue
            # Do not invent a duration or reorder words. Bound slight model
            # overshoots to the window containing the source speech.
            start = max(window.start, min(window.end, start))
            end = max(start, min(window.end, end))
            midpoint = (start + end) / 2
            if midpoint < window.own_from or midpoint > window.own_until:
                continue
            if midpoint == window.own_until and window.own_until < duration:
                continue  # exact ownership seam belongs to the next window
            result.append({"start": round(start, 3), "end": round(end, 3),
                           "text": content})
    return result
