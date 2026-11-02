"""Recognition-time SHA-256 source binding; real bytes, mocked ASR only."""
from __future__ import annotations

import hashlib

import pytest

from nass_mcp import core
from nass_mcp.media_integrity import media_sha256, require_matching_media

VIDEO = "QxC5E44QoZY"


def test_local_asr_result_stores_digest_of_actual_source_file(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    path = media / "review.wav"
    path.write_bytes(b"local-media-fixture-unique")
    monkeypatch.setattr(core, "MEDIA_ROOT", media)
    engine = core.Engine(tmp_path / "data")
    monkeypatch.setattr(engine, "check_audio", lambda _: 4.5)
    monkeypatch.setattr(engine, "speech_to_text", lambda *_:
                        ([{"start": 1, "end": 2, "text": "النص"}], "faster-whisper"))
    result = engine.transcribe_file("review.wav")
    assert result["ok"]
    assert result["recognition"]["audio_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    require_matching_media(result, media_sha256(path))
    path.write_bytes(b"another equal-length media!")
    with pytest.raises(ValueError, match="mismatch"):
        require_matching_media(result, media_sha256(path))


def test_local_media_mutation_during_asr_is_failed_not_verified(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    path = media / "changing.wav"
    path.write_bytes(b"original bytes")
    monkeypatch.setattr(core, "MEDIA_ROOT", media)
    engine = core.Engine(tmp_path / "data")
    monkeypatch.setattr(engine, "check_audio", lambda _: 4.0)
    def fake_asr(*_):
        path.write_bytes(b"changed bytes!")
        return [{"start": 0, "end": 2, "text": "لا يعتد بهذا"}], "faster-whisper"
    monkeypatch.setattr(engine, "speech_to_text", fake_asr)
    result = engine.transcribe_file("changing.wav")
    assert result["ok"] is False
    assert "changed while ASR" in result["error"]


def test_youtube_source_stores_recognition_time_hash_if_actual_audio_exists(tmp_path, monkeypatch):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"mock permitted audio")
    engine = core.Engine(tmp_path / "data")
    monkeypatch.setattr(engine, "get_captions", lambda *_: None)
    monkeypatch.setattr(engine, "acquire_audio", lambda *_: (audio, "test-media"))
    monkeypatch.setattr(engine, "speech_to_text", lambda *_:
                        ([{"start": 0, "end": 2, "text": "العلم"}], "faster-whisper"))
    monkeypatch.setattr(engine, "check_audio", lambda _: 8.0)
    result = engine.transcribe(VIDEO, mode="audio")
    assert result["ok"]
    assert result["recognition"]["audio_sha256"] == media_sha256(audio)


def test_youtube_mutation_returns_failure_instead_of_completing(tmp_path, monkeypatch):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"original media")
    engine = core.Engine(tmp_path / "data")
    monkeypatch.setattr(engine, "acquire_audio", lambda *_: (audio, "test-media"))
    def change_file(*_):
        audio.write_bytes(b"edited media")
        return [{"start": 0, "end": 2, "text": "مبدل"}], "faster-whisper"
    monkeypatch.setattr(engine, "speech_to_text", change_file)
    result = engine.transcribe(VIDEO, mode="audio")
    assert not result["ok"]
    assert "changed while ASR" in result["error"]


def test_unbound_legacy_result_is_not_backfilled_from_current_audio():
    legacy = {"recognition": {"duration_seconds": 60}}
    with pytest.raises(ValueError, match="re-transcribe"):
        require_matching_media(legacy, "a" * 64)
