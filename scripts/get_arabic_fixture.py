"""Acquire exactly one public Arabic ASR reference row for a non-redistributed test.

Audio and source reference are CC BY 4.0 / CC BY-SA 4.0 respectively.
No remote user media, access credentials or YouTube scraping.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

DATASET = "Bayanat-Labs/arabic-asr-channel-pairs"
ATTRIBUTION = "Bayanat Labs Arabic ASR Channel Pairs v0.1.0, audio from Google FLEURS (CC BY 4.0), reference from FLoRes-101 (CC BY-SA 4.0)"
MEDIA = Path(os.environ["NASS_MEDIA_DIR"])
MANIFEST = Path(os.environ.get("NASS_ARABIC_MANIFEST", "nass-arabic-eval.jsonl"))
API = "https://datasets-server.huggingface.co/rows?" + urlencode({
    "dataset": DATASET, "config": "CLEAN", "split": "test", "offset": 0, "length": 1
})


def read_bounded(url: str, size_limit: int) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Nass-MCP-Evaluation/0.5"}),
                 timeout=45) as response:
        data = response.read(size_limit + 1)
    if len(data) > size_limit:
        raise RuntimeError("External fixture exceeds size limit")
    return data


def allowed_audio_url(link: str) -> bool:
    if not isinstance(link, str) or len(link) > 4000:
        return False
    parsed = urlsplit(link)
    host = parsed.hostname
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return (host == "huggingface.co" or host == "datasets-server.huggingface.co"
            or host.endswith(".hf.co") or host.endswith(".huggingface.co"))


def main() -> None:
    info = json.loads(read_bounded(API, 350000))
    rows = info.get("rows", [])
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one public source row")
    row = rows[0]["row"]
    audio = row.get("audio")
    if not isinstance(audio, list) or len(audio) != 1 or not isinstance(audio[0], dict):
        raise RuntimeError("Unexpected audio asset schema")
    asset = audio[0]
    url = asset.get("src", "")
    if not allowed_audio_url(url):
        raise RuntimeError("Audio download host is outside approved Hugging Face origins")
    expected_sha = row.get("audio_sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise RuntimeError("No pinned audio checksum in dataset")
    raw = read_bounded(url, 6 * 1024 * 1024)
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError("Audio SHA-256 mismatch with published dataset metadata")
    if len(raw) < 3000:
        raise RuntimeError("Audio sample too small")
    reference = row.get("reference_ar")
    if not isinstance(reference, str) or len(reference.strip()) < 10:
        raise RuntimeError("No Arabic text reference")
    mime = str(asset.get("type", "")).casefold()
    ext = ".flac" if "flac" in mime else (".mp3" if "mpeg" in mime or "mp3" in mime else ".wav")
    MEDIA.mkdir(parents=True, exist_ok=True)
    name = "arabic-fleurs-test-0" + ext
    (MEDIA / name).write_bytes(raw)
    manifest_row = {
        "id": str(row["id"]),
        "audio": name,
        "reference": reference,
        # Published text does not prove that a human compared this clip to its exact speech.
        "reference_quality": "unverified",
        "language": "ar",
        "source": "https://huggingface.co/datasets/" + DATASET,
        "license": "CC BY 4.0 audio; CC BY-SA 4.0 transcript",
    }
    MANIFEST.write_text(json.dumps(manifest_row, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"source": DATASET, "split": "test", "sample_index": 0,
          "audio_bytes": len(raw), "audio_sha256_verified": True,
          "reference_characters": len(reference), "attribution": ATTRIBUTION},
          ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
