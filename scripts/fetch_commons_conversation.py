"""Fetch a self-licensed natural Arabic conversation from Wikimedia Commons.

Attribution: Sandra Hanbo, "ARABIC SPEAKING COMMUNITY Conversation hour"
(26 Jan 2023), CC BY-SA 4.0, Wikimedia Commons. This script does not
redistribute any audio or transcribed words through CI artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

URL = ("https://upload.wikimedia.org/wikipedia/commons/c/c3/"
       "ARABIC_SPEAKING_COMMUNITY_Conversation_hour.webm")
SOURCE_PAGE = ("https://commons.wikimedia.org/wiki/"
               "File:ARABIC_SPEAKING_COMMUNITY_Conversation_hour.webm")
EXPECTED_SHA1 = "868f164bcbedc117cc358b344fa305a00b741141"
EXPECTED_BYTES = 86747334
LIMIT_BYTES = 95 * 1024 * 1024


def fetch(source: str, dest: Path):
    if urlsplit(source).hostname != "upload.wikimedia.org":
        raise RuntimeError("Source not on expected Wikimedia upload host")
    digest = hashlib.sha1()
    length = 0
    with urlopen(Request(source, headers={"User-Agent": "Nass-MCP-Open-ASR/0.5 contact GitHub project"}), timeout=120) as response:
        if urlsplit(response.geturl()).hostname != "upload.wikimedia.org":
            raise RuntimeError("Unexpected cross-origin redirect")
        with dest.open("wb") as out:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                length += len(block)
                if length > LIMIT_BYTES:
                    raise RuntimeError("Source exceeds authorized test download size")
                digest.update(block)
                out.write(block)
    if length != EXPECTED_BYTES or digest.hexdigest() != EXPECTED_SHA1:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Original Wikimedia file integrity mismatch")


def main():
    media = Path(os.environ["NASS_MEDIA_DIR"])
    media.mkdir(parents=True, exist_ok=True)
    original = media / "commons-original.webm"
    result = media / "commons-arabic-conversation-30m.flac"
    try:
        fetch(URL, original)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                        "-i", str(original), "-t", "1800", "-vn",
                        "-ac", "1", "-ar", "16000", "-c:a", "flac", str(result)],
                       timeout=240, check=True, capture_output=True)
    finally:
        original.unlink(missing_ok=True)
    from nass_mcp.core import Engine
    duration = Engine().check_audio(result)
    if not 1795 <= duration <= 1805:
        raise RuntimeError("Natural conversation extraction not 30 minutes")
    print(json.dumps({
        "source_page": SOURCE_PAGE, "author": "Sandra Hanbo",
        "published": "2023-01-26", "license": "CC BY-SA 4.0",
        "original_sha1_verified": True,
        "original_bytes": EXPECTED_BYTES,
        "processed_duration_seconds": round(duration, 2),
        "processed_audio_bytes": result.stat().st_size,
        "note": "Source audio is locally cropped to first 30 min; not republished.",
    }, indent=2))


if __name__ == "__main__":
    main()
