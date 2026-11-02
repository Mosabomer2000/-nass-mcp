"""Private-pack probe: actual FFmpeg WAVs, zero human references, no uploads."""
from __future__ import annotations

import subprocess

import pytest

from nass_mcp.manual_review import file_digest
from scripts.probe_private_audit_pack import probe_private_pack


def make_wav(path):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-ar", "16000", "-ac", "1", "-y", str(path)],
        check=True, timeout=30,
    )


def result(digest):
    return {
        "is_audio_asr": True, "source": "asr:faster-whisper",
        "recognition": {
            "duration_seconds": 12.0,
            "configured_chunk_seconds": 6,
            "configured_overlap_seconds": 2,
            "audio_sha256": digest,
        },
        "segments": [
            {"start": 3.0, "end": 4.0, "text": "DO_NOT_UPLOAD_ASR_WORDS"},
            {"start": 5.2, "end": 5.6, "text": "DO_NOT_PUBLISH_PRIVATE_ASR"},
            {"start": 8.5, "end": 9.5, "text": "DO_NOT_LEAK_REVIEW_WORDS"},
        ],
    }


def test_probe_actually_parses_private_wav_and_reports_zero_accuracy(tmp_path):
    audio = tmp_path / "audio.wav"
    make_wav(audio)
    report = probe_private_pack(audio, result(file_digest(audio)),
                                context_seconds=1, controls=0)
    assert report["source_sha256_match"] is True
    assert report["private_pack_generated_on_real_source"] is True
    assert report["private_pcm_wav_probes_passed"] == 2
    assert report["review_rows"] == report["unreviewed_rows"] == 2
    assert report["human_verified_rows"] == 0
    assert report["excerpt_wer"] is None
    assert report["whole_recording_wer"] is None
    assert report["private_pack_uploaded"] is False
    assert report["sampled_audio_seconds"] > 0
    assert "DO_NOT_UPLOAD" not in str(report)
    assert "DO_NOT_LEAK" not in str(report)
    assert str(tmp_path) not in str(report)


def test_probe_rejects_unrelated_input_media_before_building_pack(tmp_path):
    audio = tmp_path / "audio.wav"
    make_wav(audio)
    with pytest.raises(ValueError, match="mismatch"):
        probe_private_pack(audio, result("c" * 64),
                           context_seconds=1, controls=0)


def test_probe_rejects_unbound_legacy_result(tmp_path):
    audio = tmp_path / "audio.wav"
    make_wav(audio)
    old = result(file_digest(audio))
    del old["recognition"]["audio_sha256"]
    with pytest.raises(ValueError, match="re-transcribe"):
        probe_private_pack(audio, old, context_seconds=1, controls=0)
