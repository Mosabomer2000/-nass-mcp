"""Bind ASR output to the exact immutable media bytes that produced it.

A filename, duration, or reviewer-side digest alone does not establish source
identity. Only a digest persisted at recognition time can do that.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def media_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_matching_media(result: dict, observed_sha256: str) -> None:
    """Fail closed on legacy results or source-content mismatch.

    For a historical ASR job, there is no cryptographic evidence linking its
    hypothesis to today's provided media. Re-run ASR to create a bound result.
    """
    metadata = result.get("recognition") if isinstance(result, dict) else None
    bound = metadata.get("audio_sha256") if isinstance(metadata, dict) else None
    if not isinstance(bound, str) or not _HEX_SHA256.fullmatch(bound):
        raise ValueError(
            "ASR result lacks a valid source-audio SHA256; re-transcribe the "
            "exact media with the current Nass version before accuracy scoring"
        )
    if not isinstance(observed_sha256, str) or not _HEX_SHA256.fullmatch(observed_sha256):
        raise ValueError("Invalid local source-audio SHA256")
    if not hmac.compare_digest(bound, observed_sha256):
        raise ValueError("ASR source-audio SHA256 mismatch: not the media used for recognition")
