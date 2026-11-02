"""Offline regression for paginated, provenance-preserving MCP transcript delivery."""
import json
from pathlib import Path
import pytest
from nass_mcp.delivery import render, transcript_page, verification_page, quality_report

JOB = "b" * 32
DATA = {"ok": True, "video_id": "QxC5E44QoZY", "language": "ar",
        "source": "asr:faster-whisper", "is_audio_asr": True,
        "segments": [{"start": 0, "end": 1.4, "text": "بسم الله"},
                     {"start": 3, "end": 4, "text": "الحمد لله"}],
        "verification": {"captions_source": "youtube-transcript-api:ar:manual",
                         "captions_segments": [{"start": 0, "end": 2, "text": "بسم الله الرحمن الرحيم"}]},
        "attempts": [{"stage": "audio", "message": "secret-test-credential-abc"}]}


class Store:
    def __init__(self, root, data=DATA, state="completed"):
        self.base = root / "jobs"
        p = self.base / JOB
        p.mkdir(parents=True)
        (p / "result.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        self.state = state

    def get_status(self, job_id):
        if job_id != JOB:
            raise ValueError("No such job")
        return {"state": self.state, "finished_at": "2026-11-02T00:00:00Z"}


def test_all_five_formats():
    assert "بسم الله" in render(DATA, "txt")
    assert "00:00:01,400" in render(DATA, "srt")
    assert "WEBVTT" in render(DATA, "vtt")
    assert "t=3s" in render(DATA, "md")
    assert json.loads(render(DATA, "json"))["is_audio_asr"] is True


def test_json_does_not_include_raw_provider_error():
    assert "secret-test-credential-abc" not in render(DATA, "json")


def test_json_page_roundtrip_unicode(tmp_path):
    store = Store(tmp_path)
    chunks, pos = [], 0
    for _ in range(500):
        result = transcript_page(store, JOB, "json", offset=pos, max_chars=19)
        chunks.append(result["content"])
        if result["next_offset"] is None:
            break
        pos = result["next_offset"]
    assert "".join(chunks) == render(DATA, "json")
    assert result["source"] == DATA["source"]


def test_rejects_bad_bounds_or_incomplete_job(tmp_path):
    s = Store(tmp_path)
    for value in (-1, True, 2000000):
        with pytest.raises(ValueError):
            transcript_page(s, JOB, offset=value)
    with pytest.raises(ValueError):
        transcript_page(s, JOB, max_chars=16001)
    s.state = "running"
    with pytest.raises(ValueError):
        transcript_page(s, JOB)


def test_verification_tracks_independent(tmp_path):
    s = Store(tmp_path)
    a = verification_page(s, JOB, "audio")
    b = verification_page(s, JOB, "captions")
    assert a["source"] != b["source"]
    assert a["segments"][0]["text"] != b["segments"][0]["text"]


def test_no_fake_accuracy(tmp_path):
    s = Store(tmp_path, dict(DATA, segments=[{"start": 0, "end": 5, "text": "repeat"},
        {"start": 1, "end": 6, "text": "repeat"},
        {"start": 2, "end": 7, "text": "repeat"},
        {"start": 3, "end": 8, "text": "repeat"},
        {"start": 200, "end": 201, "text": "new"}]))
    x = quality_report(s, JOB)
    assert x["accuracy_score"] is None
    kinds = {a["type"] for a in x["anomalies"]}
    assert "long_untranscribed_gap" in kinds
    assert "four_identical_consecutive_segments" in kinds


def test_invalid_video_ref_not_linked():
    d = dict(DATA, video_id="../../../secret")
    assert "https://www.youtube.com" not in render(d, "md")
