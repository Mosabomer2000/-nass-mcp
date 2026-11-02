"""Reproducible, redacted ASR model provenance tests."""
import json
from nass_mcp.core import Result, recognition_provenance


def test_whisper_settings_and_effective_windows(monkeypatch):
    monkeypatch.setenv("NASS_WHISPER_MODEL", "small")
    monkeypatch.setenv("NASS_ASR_CHUNK_SECONDS", "20")
    monkeypatch.setenv("NASS_ASR_OVERLAP_SECONDS", "4")
    monkeypatch.setenv("NASS_INITIAL_PROMPT", "private theological keyword")
    meta = recognition_provenance("faster-whisper", 88)
    assert meta["model"] == "small"
    assert meta["planned_windows"] == 6
    assert "private" not in json.dumps(meta)


def test_absolute_custom_model_path_not_exposed(monkeypatch):
    monkeypatch.setenv("NASS_WHISPER_MODEL", "/home/user/private-model")
    monkeypatch.setenv("NASS_ASR_CHUNK_SECONDS", "0")
    meta = recognition_provenance("faster-whisper", 95)
    assert meta["model"] == "custom-local-model"
    assert meta["planned_windows"] == 1
    assert "/home" not in json.dumps(meta)


def test_result_contains_model_provenance():
    metadata = {"backend": "faster-whisper", "model": "small",
                "planned_windows": 4}
    result = Result("local-file", "asr:faster-whisper",
                    [{"start": 1, "end": 2, "text": "العلم"}],
                    "ar", recognition=metadata).to_dict()
    assert result["recognition"] == metadata
    assert result["is_audio_asr"]


def test_no_model_info_in_caption_only_result():
    result = Result("QxC5E44QoZY", "captions:manual").to_dict()
    assert result["recognition"] is None
