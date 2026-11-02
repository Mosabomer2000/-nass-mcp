"""Fetch ten NahwAI human-reviewed Arabic speech samples, for evaluation only.

Dataset: NahwAI/arabic-tashkeel-speech, CC BY 4.0. No licensed audio or
transcript text is uploaded to public CI artifacts.
"""
from __future__ import annotations
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

DATASET = "NahwAI/arabic-tashkeel-speech"
OFFSETS = (0, 109, 218, 327, 436, 545, 654, 763, 872, 981)
MEDIA = Path(os.environ["NASS_MEDIA_DIR"])
OUTPUT = Path(os.environ.get("NASS_NAHW_MANIFEST", "nass-nahw-eval.jsonl"))


def read_bounded(url: str, limit: int) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Nass-MCP-Open-ASR/0.5"}),
                 timeout=35) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Response exceeds approved limit")
    return data


def approved_asset(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 4000:
        return False
    p = urlsplit(url)
    if p.scheme != "https" or p.username or p.password or not p.hostname:
        return False
    try:
        ipaddress.ip_address(p.hostname)
        return False
    except ValueError:
        pass
    host = p.hostname
    return host in ("huggingface.co", "datasets-server.huggingface.co") or host.endswith(".huggingface.co") or host.endswith(".hf.co")


def main() -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    manifest = []
    shas = []
    for index, offset in enumerate(OFFSETS):
        endpoint = "https://datasets-server.huggingface.co/rows?" + urlencode({
            "dataset": DATASET, "config": "default", "split": "train",
            "offset": offset, "length": 1})
        data = json.loads(read_bounded(endpoint, 350000))
        rows = data.get("rows") or []
        if len(rows) != 1:
            raise RuntimeError("Expected one NahwAI dataset row")
        row = rows[0].get("row") or {}
        reference = row.get("transcription")
        audio = row.get("audio")
        if not isinstance(reference, str) or len(reference.strip()) < 5:
            raise RuntimeError("Missing approved Arabic reference")
        if not isinstance(audio, list) or len(audio) != 1 or not isinstance(audio[0], dict):
            raise RuntimeError("Unexpected NahwAI audio field")
        src = audio[0].get("src")
        if not approved_asset(src):
            raise RuntimeError("Audio asset URL not on allowed Hugging Face host")
        raw = read_bounded(src, 5 * 1024 * 1024)
        if len(raw) < 1000:
            raise RuntimeError("Audio fixture too short or unavailable")
        mime = str(audio[0].get("type") or "").lower()
        ext = ".flac" if "flac" in mime else (".mp3" if "mpeg" in mime or "mp3" in mime else ".wav")
        name = f"nahw-human-reviewed-{index:02d}" + ext
        (MEDIA / name).write_bytes(raw)
        shas.append(hashlib.sha256(raw).hexdigest())
        manifest.append({
            "id": f"nahw-train-{offset}", "audio": name, "reference": reference,
            "reference_quality": "human_verified", "language": "ar",
            "source": "https://huggingface.co/datasets/" + DATASET,
            "license": "CC BY 4.0",
        })
    OUTPUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in manifest) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset": DATASET, "split": "train", "row_offsets": OFFSETS,
        "recordings": len(manifest),
        "download_sha256": shas,
        "reference_provenance": "Publisher states every recording was reviewed and approved by a human annotator.",
        "review_not_independently_repeated_by_nass": True,
        "recording_audio_and_reference_text_not_published": True,
        "license": "CC BY 4.0",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
