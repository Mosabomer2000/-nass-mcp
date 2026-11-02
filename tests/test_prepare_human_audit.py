"""End-to-end *local preparation* acceptance; no simulated human review."""
from __future__ import annotations

import json
import subprocess

import pytest

from nass_mcp.manual_review import evaluate_reviews, file_digest
from scripts.prepare_human_audit import prepare_audit


def fixture_result(digest):
    return {
        "ok": True,
        "is_audio_asr": True, "source": "asr:faster-whisper",
        "recognition": {
            "backend": "faster-whisper",
            "duration_seconds": 12.0,
            "configured_chunk_seconds": 6,
            "configured_overlap_seconds": 2,
            "audio_sha256": digest,
        },
        "segments": [
            {"start": 0.2, "end": 1.5, "text": "PRIVATE_MACHINE_UTTERANCE"},
            {"start": 5.1, "end": 5.7, "text": "SECRET_MACHINE_OUTPUT"},
            {"start": 9.0, "end": 9.8, "text": "PRIVATE_ASR_WORDS"},
        ],
    }


def make_audio(path):
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-ar", "16000", "-ac", "1", str(path),
    ], check=True, timeout=40)


def test_private_audit_pack_contains_no_recognized_words_or_false_accuracy(tmp_path):
    audio = tmp_path / "real-bytes.wav"
    make_audio(audio)
    data = fixture_result(file_digest(audio))
    target = tmp_path / "private"
    report = prepare_audit(audio, data, target, context_seconds=1,
                           control_intervals=0)
    assert report["clip_count"] == 2
    assert report["human_verified_rows"] == 0
    assert report["full_recording_wer"] is None
    assert report["review_required"] is True
    assert (target / "clip_0001.wav").is_file()
    assert (target / "clip_0002.wav").is_file()
    html = (target / "review.html").read_text("utf-8")
    assert "PRIVATE_MACHINE_UTTERANCE" not in html
    assert "SECRET_MACHINE_OUTPUT" not in html
    pending = [json.loads(x) for x in
               (target / "annotations-pending.jsonl").read_text("utf-8").splitlines()]
    assert len(pending) == 2
    assert all(row["reference_text"] == "" for row in pending)
    assert all(row["reviewer_attestation"] is False for row in pending)
    assert all(row["review_state"] == "pending" for row in pending)
    outcome = evaluate_reviews(data, pending, file_digest(audio))
    assert outcome["scored_rows"] == 0
    assert outcome["aggregate"]["human_verified_micro_wer"] is None
    assert outcome["full_recording_wer"] is None
    assert "PRIVATE_MACHINE_UTTERANCE" not in (
        target / "index.json").read_text("utf-8")


def test_wrong_media_digest_refuses_to_create_private_review_folder(tmp_path):
    audio = tmp_path / "real-bytes.wav"
    make_audio(audio)
    result = fixture_result("0" * 64)
    target = tmp_path / "private"
    with pytest.raises(ValueError, match="mismatch"):
        prepare_audit(audio, result, target, context_seconds=1,
                      control_intervals=0)
    assert not target.exists()


def test_old_unbound_asr_cannot_generate_false_review_pack(tmp_path):
    audio = tmp_path / "audio.wav"
    make_audio(audio)
    result = fixture_result(file_digest(audio))
    del result["recognition"]["audio_sha256"]
    with pytest.raises(ValueError, match="re-transcribe"):
        prepare_audit(audio, result, tmp_path / "pack", context_seconds=1,
                      control_intervals=0)
    assert not (tmp_path / "pack").exists()
