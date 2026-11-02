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
SAMPLES = int(os.environ.get("NASS_ARABIC_SAMPLES", "1"))
if not 1 <= SAMPLES <= 10:
    raise ValueError("Arabic evaluation sample count must be in 1..10")
API = "https://datasets-server.huggingface.co/rows?" + urlencode({
    "dataset": DATASET, "config": "CLEAN", "split": "test", "offset": 0, "length": SAMPLES
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
    if len(rows) != SAMPLES:
        raise RuntimeError("Dataset API returned unexpected sample count")
    MEDIA.mkdir(parents=True, exist_ok=True)
    examples = []
    total_bytes = 0
    for index, wrapped in enumerate(rows):
        row = wrapped["row"]
        audio = row.get("audio")
        if not isinstance(audio, list) or len(audio) != 1 or not isinstance(audio[0], dict):
            raise RuntimeError("Unexpected audio asset schema")
        asset = audio[0]
        url = asset.get("src", "")
        if not allowed_audio_url(url):
            raise RuntimeError("Audio download host outside approved Hugging Face origins")
        expected_sha = row.get("audio_sha256")
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise RuntimeError("Dataset lacks sample audio SHA-256")
        raw = read_bounded(url, 6 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise RuntimeError("Downloaded audio does not match its published checksum")
        if len(raw) < 3000:
            raise RuntimeError("Audio sample too small")
        reference = row.get("reference_ar")
        if not isinstance(reference, str) or len(reference.strip()) < 10:
            raise RuntimeError("No Arabic text reference")
        mime = str(asset.get("type", "")).casefold()
        ext = ".flac" if "flac" in mime else (".mp3" if "mpeg" in mime or "mp3" in mime else ".wav")
        name = f"arabic-fleurs-test-{index}" + ext
        (MEDIA / name).write_bytes(raw)
        total_bytes += len(raw)
        examples.append({
            "id": str(row["id"]), "audio": name, "reference": reference,
            # A published reading prompt is not proof of manual audio/reference alignment.
            "reference_quality": "unverified", "language": "ar",
            "source": "https://huggingface.co/datasets/" + DATASET,
            "license": "CC BY 4.0 audio; CC BY-SA 4.0 transcript",
        })
    MANIFEST.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in examples) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "source": DATASET, "split": "test", "sample_start": 0,
        "sample_count": SAMPLES, "audio_bytes": total_bytes,
        "all_audio_sha256_verified": True,
        "attribution": ATTRIBUTION,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
