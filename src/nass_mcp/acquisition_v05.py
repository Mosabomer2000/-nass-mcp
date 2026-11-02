"""Operator-configured Invidious caption fallback and acquisition diagnostics."""
from __future__ import annotations
from importlib import metadata
import json
import os
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LANGUAGE = re.compile(r"^(?:[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*|auto)$")

class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _invidious_base(raw: str) -> str:
    p = urlsplit(raw.strip())
    if p.scheme not in ("https", "http") or not p.hostname:
        raise ValueError("Invidious URL must be an absolute URL")
    if p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
        raise ValueError("Invidious URL must be a simple instance origin")
    if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("HTTP is only permitted for locally hosted Invidious")
    if p.port is not None and not 1 <= p.port <= 65535:
        raise ValueError("Invalid Invidious port")
    return raw.strip().rstrip("/")

def _read_limited(request: Request, maximum: int, timeout: float) -> bytes:
    opener = build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Invidious returned HTTP {response.status}")
            body = response.read(maximum + 1)
    except HTTPError as exc:
        raise RuntimeError(f"Invidious returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Invidious endpoint unavailable") from exc
    if len(body) > maximum:
        raise RuntimeError("Invidious response exceeds configured size limit")
    return body

def fetch_invidious_captions(video_id: str, language: str,
                            parse_vtt: Callable[[str], list[dict]], *,
                            instance: str | None = None,
                            reader: Callable[[Request, int, float], bytes] = _read_limited
                            ) -> tuple[list[dict], str]:
    """Only request the configured origin; ignore URLs returned by upstream JSON."""
    if not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID")
    if not _LANGUAGE.fullmatch(language):
        raise ValueError("Invalid caption language")
    origin = _invidious_base(instance or os.environ.get("NASS_INVIDIOUS_URL", ""))
    endpoint = origin + f"/api/v1/captions/{video_id}"
    headers = {"Accept": "application/json", "User-Agent": "Nass-MCP/0.5"}
    try:
        listed = json.loads(reader(Request(endpoint, headers=headers), 1024 * 1024, 15).decode("utf-8"))
        tracks = listed["captions"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Invalid Invidious caption listing") from exc
    if not isinstance(tracks, list) or len(tracks) > 1000:
        raise RuntimeError("Invalid Invidious caption listing")
    candidates = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        code, label = track.get("languageCode"), track.get("label")
        if not isinstance(code, str) or not _LANGUAGE.fullmatch(code):
            continue
        if not isinstance(label, str) or not 0 < len(label) <= 200:
            continue
        if language == "auto" or code.lower() == language.lower() or code.lower().startswith(language.lower() + "-"):
            candidates.append((code, label))
    if not candidates:
        raise RuntimeError("Invidious has no captions in requested language")
    candidates.sort(key=lambda pair: (pair[0].lower() != language.lower(), "automatic" in pair[1].lower()))
    code, label = candidates[0]
    # A supplied track 'url' may point to another host; never fetch it.
    target = endpoint + "?" + urlencode({"label": label})
    vtt = reader(Request(target, headers={"Accept": "text/vtt", "User-Agent": "Nass-MCP/0.5"}),
                 8 * 1024 * 1024, 30).decode("utf-8-sig")
    if "-->" not in vtt:
        raise RuntimeError("Invidious returned no valid WebVTT timestamps")
    segments = parse_vtt(vtt)
    if not segments:
        raise RuntimeError("Invidious returned no parseable caption segments")
    return segments, f"invidious-captions:{code}"

def acquisition_report() -> dict:
    """Configuration visibility; does not claim provider availability or success."""
    packages = {}
    for name in ("yt-dlp", "bgutil-ytdlp-pot-provider", "yt-dlp-getpot-wpc"):
        try:
            packages[name] = {"installed": True, "version": metadata.version(name)}
        except metadata.PackageNotFoundError:
            packages[name] = {"installed": False}
    configured = bool(os.environ.get("NASS_INVIDIOUS_URL"))
    valid = False
    if configured:
        try:
            _invidious_base(os.environ["NASS_INVIDIOUS_URL"])
            valid = True
        except ValueError:
            pass
    return {
        "invidious_configured": configured,
        "invidious_url_valid": valid,
        "mweb_pot_enabled": os.environ.get("NASS_ENABLE_MWEB_POT") == "1",
        "packages": packages,
        "notice": "Configuration and package installation do not prove YouTube extraction or transcription success.",
    }
