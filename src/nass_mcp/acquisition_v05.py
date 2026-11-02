"""Optional Invidious caption acquisition for Nass; explicit origin and bounded reads.

This backend does not bypass authorization or create captions from missing speech.
It does not follow HTTP redirects and never uses URLs supplied by the captions API.
"""
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
_LANG = re.compile(r"^(?:[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*|auto)$")


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _origin(config: str) -> str:
    value = config.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invidious requires an absolute instance origin")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Invidious origin must not include credentials, path or query")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid Invidious port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid Invidious port")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Non-local Invidious requires HTTPS")
    return value.rstrip("/")


def _fetch(req: Request, limit: int, timeout: float) -> bytes:
    opener = build_opener(_NoRedirects)
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError("Invidious returned an unexpected response")
            body = response.read(limit + 1)
    except HTTPError as exc:
        raise RuntimeError(f"Invidious HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Invidious endpoint unavailable") from exc
    if len(body) > limit:
        raise RuntimeError("Invidious response exceeds maximum size")
    return body


def fetch_invidious_captions(video_id: str, language: str,
                            parse_vtt: Callable[[str], list[dict]], *,
                            instance: str | None = None,
                            reader: Callable[[Request, int, float], bytes] = _fetch
                            ) -> tuple[list[dict], str]:
    """Find and fetch one track from a configured Invidious instance.

    The listing's URL field is never fetched: requests use only the configured origin.
    reader injection is used by isolated tests, not exposed as an MCP argument.
    """
    if not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID")
    if not _LANG.fullmatch(language):
        raise ValueError("Invalid language")
    base = _origin(instance if instance is not None else os.environ.get("NASS_INVIDIOUS_URL", ""))
    path = "/api/v1/captions/" + video_id
    header = {"Accept": "application/json", "User-Agent": "Nass-MCP/0.5"}
    try:
        listing = json.loads(reader(Request(base + path, headers=header), 1048576, 15).decode("utf-8"))
        tracks = listing["captions"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Invalid Invidious caption listing") from exc
    if not isinstance(tracks, list) or len(tracks) > 1000:
        raise RuntimeError("Invalid Invidious caption listing")
    valid = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        code, label = track.get("languageCode"), track.get("label")
        if not isinstance(code, str) or not isinstance(label, str) or len(label) > 200:
            continue
        if not label or not _LANG.fullmatch(code):
            continue
        if language == "auto" or code.lower() == language.lower() or code.lower().startswith(language.lower() + "-"):
            valid.append((code, label))
    if not valid:
        raise RuntimeError("No captions in requested language")
    valid.sort(key=lambda item: (item[0].lower() != language.lower(),
                                  "auto-generated" in item[1].lower() or "automatic" in item[1].lower()))
    code, label = valid[0]
    # Do not follow a URL delivered by a third-party API.
    url = base + path + "?" + urlencode({"label": label})
    vtt = reader(Request(url, headers={"Accept": "text/vtt", "User-Agent": "Nass-MCP/0.5"}),
                 8 * 1024 * 1024, 30).decode("utf-8-sig")
    if "-->" not in vtt:
        raise RuntimeError("Invalid or missing WebVTT")
    segments = parse_vtt(vtt)
    if not segments:
        raise RuntimeError("No parseable captions")
    return segments, "invidious-captions:" + code


def acquisition_report() -> dict:
    packages = {}
    for name in ("yt-dlp", "bgutil-ytdlp-pot-provider", "yt-dlp-getpot-wpc"):
        try:
            packages[name] = {"installed": True, "version": metadata.version(name)}
        except metadata.PackageNotFoundError:
            packages[name] = {"installed": False}
    valid = False
    config = os.environ.get("NASS_INVIDIOUS_URL", "")
    if config:
        try:
            _origin(config)
            valid = True
        except ValueError:
            pass
    return {
        "invidious_configured": bool(config),
        "invidious_origin_valid": valid,
        "mweb_pot_opt_in": os.environ.get("NASS_ENABLE_MWEB_POT") == "1",
        "packages": packages,
        "note": "Package/configuration presence does not establish media access or ASR success.",
    }
