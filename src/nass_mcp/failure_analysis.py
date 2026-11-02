"""Classify acquisition failure evidence without claiming a root cause or leaking raw errors."""
from __future__ import annotations

import re
from collections import Counter


def classify_failure(message: str) -> dict:
    """A conservative, diagnostic-only classification of the provider-reported error."""
    raw = str(message or "").casefold()
    if any(t in raw for t in ("sign in to confirm", "not a bot", "requestblocked", "bot check",
                              "captcha", "login_required")):
        code, next_step = "youtube_access_challenge", "Test a permitted local host; a PO token alone may not fix network-level access."
    elif any(t in raw for t in ("private video", "members-only", "video is private", "authentication required")):
        code, next_step = "access_restricted", "Do not attempt to bypass video permissions."
    elif any(t in raw for t in ("403 forbidden", "http error 403", "http 403", "forbidden")):
        code, next_step = "http_forbidden", "Inspect player and PO-token configuration; 403 alone does not identify its cause."
    elif any(t in raw for t in ("429", "too many requests", "rate limit")):
        code, next_step = "rate_limited", "Use bounded backoff and reduce request frequency."
    elif any(t in raw for t in ("optional ", "not installed", "no module named", "modulenotfounderror",
                                 "dependency missing", "not configured")):
        code, next_step = "dependency_unavailable", "Install or configure this optional provider on the host."
    elif any(t in raw for t in ("no captions", "no subtitle", "subtitle disabled", "no requested language")):
        code, next_step = "captions_unavailable", "Use audio recognition when authorized and accessible."
    elif any(t in raw for t in ("timeout", "timed out")):
        code, next_step = "timeout", "Check host network latency and bounded provider timeout."
    elif any(t in raw for t in ("video unavailable", "video not found", "deleted video")):
        code, next_step = "media_unavailable", "Verify that the public video remains available."
    else:
        code, next_step = "unknown", "Inspect private operator logs without exposing secrets."
    return {"category": code, "next_step": next_step}


def diagnose_attempts(attempts: list[dict]) -> dict:
    """Reduce a potentially sensitive raw attempt ledger to safe structured evidence."""
    attempts = attempts if isinstance(attempts, list) else []
    observed, counts = [], Counter()
    for attempt in attempts[:200]:
        if not isinstance(attempt, dict):
            continue
        stage = re.sub(r"[^a-z0-9_/-]", "", str(attempt.get("stage", "")).lower())[:30]
        provider = re.sub(r"[^a-zA-Z0-9_.:/-]", "", str(attempt.get("provider", "")))[:90]
        success = attempt.get("ok") is True
        category = "success" if success else classify_failure(attempt.get("message", ""))["category"]
        counts[category] += 1
        observed.append({"stage": stage, "provider": provider,
                         "success": success, "category": category})
    return {"total_attempts": len(observed), "categories": dict(counts), "attempts": observed,
            "notice": "Provider observations are not proof of a root cause, transcript accuracy or successful ASR."}
