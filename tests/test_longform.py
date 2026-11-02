"""Long-recording chunk planning and true decoder-window regression cases."""
from __future__ import annotations
from types import SimpleNamespace
import subprocess

import pytest

from nass_mcp import core
from nass_mcp.longform import Window, combine_segments, plan_windows


def test_windows_cover_lecture_without_timestamp_ownership_gaps():
    items = plan_windows(7201, 480, 4)
    assert len(items) > 10
    assert items[0].start == 0
    assert items[-1].end == 7201
    assert items[0].own_from == 0
    assert items[-1].own_until == 7201
    for left, right in zip(items, items[1:]):
        assert right.start == left.end - 4
        assert left.own_until == right.own_from
        assert left.own_until > right.start


def test_midpoint_ownership_removes_duplicate_overlap():
    windows = plan_windows(10, seconds=6, overlap=2)
    assert [(x.start, x.end) for x in windows] == [(0, 6), (4, 10)]
    original = [{"start": 1, "end": 2, "text": "أول"},
                {"start": 4, "end": 6, "text": "مشترك"}]
    second = [{"start": 0, "end": 2, "text": "مشترك"},
              {"start": 2, "end": 4, "text": "أخير"}]
    output = combine_segments(windows, [original, second], 10)
    assert [s["text"] for s in output] == ["أول", "مشترك", "أخير"]
    assert output[-1]["start"] == 6


def test_missing_decoder_window_is_not_silent_success():
    with pytest.raises(ValueError):
        combine_segments(plan_windows(11, 6, 2), [[]], 11)


@pytest.mark.parametrize("bad", [-1, 0, float("nan")])
def test_duration_validation(bad):
    with pytest.raises(ValueError):
        plan_windows(bad)


@pytest.mark.parametrize("chunk,overlap", [(4, 2), (10, -1), (10, 5)])
def test_overlap_validation(chunk, overlap):
    with pytest.raises(ValueError):
        plan_windows(90, chunk, overlap)


def test_real_ffmpeg_chunks_and_mock_asr_model(tmp_path, monkeypatch):
    """Real slicing of media, mocked model only; no network or weights needed."""
    audio = tmp_path / "multi.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                    "-ar", "16000", "-ac", "1", str(audio)],
                   timeout=35, check=True)
    calls = []

    class FakeModel:
        def transcribe(self, path, **kwargs):
            from pathlib import Path
            excerpt = Path(path)
            engine = core.Engine(tmp_path)
            actual_duration = engine.check_audio(excerpt)
            calls.append((actual_duration, kwargs))
            return iter([SimpleNamespace(start=1.0, end=min(2.0, actual_duration),
                                         text=f"مقطع-{len(calls)}")]), {}

    monkeypatch.setattr(core, "load_whisper_model", lambda *args: FakeModel())
    monkeypatch.setenv("NASS_ASR_CHUNK_SECONDS", "6")
    monkeypatch.setenv("NASS_ASR_OVERLAP_SECONDS", "2")
    engine = core.Engine(tmp_path)
    out = engine.faster_whisper_asr(audio, "ar")
    assert len(calls) == 3
    assert len(out) == 3
    assert out[0]["start"] == 1.0
    assert out[-1]["start"] == 9.0
    assert all(out[i]["start"] <= out[i+1]["start"] for i in range(len(out)-1))


def test_short_clip_stays_on_previous_one_pass_path(tmp_path, monkeypatch):
    class Model:
        def transcribe(self, path, **kwargs):
            return iter([SimpleNamespace(start=0, end=1, text="واحد")]), {}

    monkeypatch.setattr(core, "load_whisper_model", lambda *a: Model())
    monkeypatch.setenv("NASS_ASR_CHUNK_SECONDS", "480")
    audio = tmp_path / "short.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=1000:duration=1", "-ar", "16000",
                    "-ac", "1", str(audio)], check=True)
    out = core.Engine(tmp_path).faster_whisper_asr(audio, "ar")
    assert out[0]["text"] == "واحد"
