"""Resource snapshots for real Nass acceptance runs, without external agents.

The reported ru_maxrss is a process lifetime peak, *not* exact per-task usage.
FFmpeg is a child process whose peak is separately recorded by POSIX.
"""
from __future__ import annotations

import math
import sys


def snapshot_process() -> dict | None:
    try:
        import resource
        parent = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        unit = 1024 * 1024 if sys.platform == "darwin" else 1024
        return {
            "platform": sys.platform,
            "process_peak_rss_mb": round(parent.ru_maxrss / unit, 2),
            "terminated_child_max_peak_rss_mb": round(children.ru_maxrss / unit, 2),
            "total_user_cpu_seconds": parent.ru_utime + children.ru_utime,
            "total_system_cpu_seconds": parent.ru_stime + children.ru_stime,
        }
    except (ImportError, AttributeError, OSError):
        return None


def resource_delta(before: dict | None, after: dict | None) -> dict:
    if before is None or after is None:
        return {"available": False, "note": "POSIX process accounting unavailable."}
    return {
        "available": True,
        "platform": after["platform"],
        "process_peak_rss_mb_since_process_start": after["process_peak_rss_mb"],
        "terminated_child_max_peak_rss_mb_since_process_start": after["terminated_child_max_peak_rss_mb"],
        "user_cpu_seconds_during_test": round(max(0.0, after["total_user_cpu_seconds"]-before["total_user_cpu_seconds"]), 3),
        "system_cpu_seconds_during_test": round(max(0.0, after["total_system_cpu_seconds"]-before["total_system_cpu_seconds"]), 3),
        "interpretation": ("Peak values are lifetime high-water marks and not per-job memory "
                           "deltas or hard RAM bounds. Child peak is per terminated child, not "
                           "an aggregate of concurrent child RSS. This does not measure GPU VRAM."),
    }
