"""Reproducible-index NahwAI human-reviewed Arabic speech benchmark loader.

This tests open CC BY 4.0 recordings but publishes *only* metrics. The publisher
states each utterance was reviewed by a human; Nass has not independently
re-audited each utterance.
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
BASES = (0, 210, 420, 630, 840)
IN_BLOCK = (0, 7, 14, 21, 28, 35, 42, 49)
MEDIA = Path(os.environ["NASS_MEDIA_DIR"])
OUTPUT = Path(os.environ.get("NASS_NAHW_MANIFEST", "nass-nahw-eval.jsonl"))


def read_bounded(url: str, limit: int) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Nass-MCP-Open-ASR/0.5"}),
                 timeout=40) as response:
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
    sha256s = []
    speaker_ids = set()
    selected_offsets = []
    for base in BASES:
        endpoint = "https://datasets-server.huggingface.co/rows?" + urlencode({
            "dataset": DATASET, "config": "default", "split": "train",
            "offset": base, "length": 50})
        data = json.loads(read_bounded(endpoint, 3 * 1024 * 1024))
        rows = data.get("rows") or []
        if len(rows) != 50:
            raise RuntimeError("Expected exactly 50 public dataset records per request")
        for inner in IN_BLOCK:
            offset = base + inner
            row = rows[inner].get("row") or {}
            reference = row.get("transcription")
            audio = row.get("audio")
            if not isinstance(reference, str) or len(reference.strip()) < 5:
                raise RuntimeError("Missing approved Arabic text reference")
            if not isinstance(audio, list) or len(audio) != 1 or not isinstance(audio[0], dict):
                raise RuntimeError("Unexpected NahwAI audio asset")
            src = audio[0].get("src")
            if not approved_asset(src):
                raise RuntimeError("Asset is outside approved Hugging Face hosts")
            raw = read_bounded(src, 5 * 1024 * 1024)
            if len(raw) < 1000:
                raise RuntimeError("Downloaded speech file is implausibly small")
            mime = str(audio[0].get("type") or "").lower()
            ext = ".flac" if "flac" in mime else (".mp3" if "mpeg" in mime or "mp3" in mime else ".wav")
            name = f"nahw-human-reviewed-{len(manifest):02d}" + ext
            (MEDIA / name).write_bytes(raw)
            sha256s.append(hashlib.sha256(raw).hexdigest())
            selected_offsets.append(offset)
            speaker_ids.add(str(row.get("speaker_id", "unknown")))
            manifest.append({
                "id": f"nahw-train-{offset}", "audio": name,
                "reference": reference, "reference_quality": "human_verified",
                "language": "ar", "source": "https://huggingface.co/datasets/" + DATASET,
                "license": "CC BY 4.0",
            })
    if len(manifest) != 40 or len(set(selected_offsets)) != 40:
        raise RuntimeError("Nonunique or incomplete benchmark selection")
    OUTPUT.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in manifest) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset": DATASET, "split": "train", "row_offsets": selected_offsets,
        "recordings": len(manifest), "speaker_groups": len(speaker_ids),
        "digest_of_downloaded_audio_sha256s": hashlib.sha256("".join(sha256s).encode()).hexdigest(),
        "reference_provenance": "Publisher says each recording was reviewed and approved by a human annotator.",
        "review_not_independently_repeated_by_nass": True,
        "audio_and_reference_text_not_published": True,
        "license": "CC BY 4.0",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
