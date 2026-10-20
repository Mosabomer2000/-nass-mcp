"""Deterministic offline regression tests for niche-provider integrations."""
import json
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from nass_mcp import core

VID = "QxC5E44QoZY"


def test_go_caption_backend_parses_srt(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(core.shutil, "which", lambda command: "/fake/yt-transcript" if command == "yt-transcript" else None)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[0] == "/fake/yt-transcript"
        assert "-lang" in args and args[args.index("-lang") + 1] == "ar"
        output = Path(args[args.index("-out") + 1])
        (output / f"some title__{VID}.ar.srt").write_text(
            "1\n00:00:01,100 --> 00:00:03,000\nحديث شريف\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(core.subprocess, "run", run)
    segments, method = e.go_captions(VID, "ar", tmp_path / "go")
    assert method.startswith("yt-transcript-go")
    assert segments[0]["start"] == pytest.approx(1.1)
    assert segments[0]["text"] == "حديث شريف"
    assert len(calls) == 1


def test_go_captions_no_misleading_stale_output(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(core.shutil, "which", lambda c: "/bin/yt-transcript")
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: None)
    directory = tmp_path / "go"
    directory.mkdir()
    (directory / "wrong_video__dQw4w9WgXcQ.en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nNot target\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no readable"):
        e.go_captions(VID, "ar", directory)


def test_go_audio_adapter_exact_itag_and_target(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(core.shutil, "which", lambda cmd: "/bin/youtubedr")
    def run(args, **kwargs):
        assert args[:4] == ["/bin/youtubedr", "download", "-q", "140"]
        assert args[-1] == core.canonical_url(VID)
        out = Path(args[args.index("-d") + 1]) / args[args.index("-o") + 1]
        out.write_bytes(b"original audio content")
    monkeypatch.setattr(core.subprocess, "run", run)
    output = e.youtubedr_audio(VID, tmp_path / "go_audio")
    assert output.name == "audio.m4a"
    assert output.read_bytes() == b"original audio content"


def test_node_adapter_uses_local_fixed_script(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(core.shutil, "which", lambda cmd: "/bin/node")
    script = Path(core.__file__).parent / "_node" / "youtubejs_audio.mjs"
    assert script.is_file()
    monkeypatch.delenv("NASS_YOUTUBEJS_SCRIPT", raising=False)
    def run(args, **kwargs):
        assert args[:3] == ["/bin/node", str(script), VID]
        assert kwargs.get("timeout")
        Path(args[3]).write_bytes(b"original audio content")
    monkeypatch.setattr(core.subprocess, "run", run)
    assert e.youtubejs_audio(VID, tmp_path / "js").exists()


def test_all_other_audio_fail_niche_go_works(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setenv("NASS_AUDIO_CACHE", "0")
    fake = tmp_path / "ok.m4a"
    fake.write_bytes(b"fake")
    def failure(*args):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(e, "ytdlp_audio", failure)
    monkeypatch.setattr(e, "pytubefix_audio", failure)
    monkeypatch.setattr(e, "youtubejs_audio", failure)
    monkeypatch.setattr(e, "youtubedr_audio", lambda *args: fake)
    monkeypatch.setattr(e, "check_audio", lambda *_: 13)
    ledger = []
    path, source = e.acquire_audio(VID, tmp_path / "work", ledger)
    assert source == "youtubedr"
    assert path == fake
    assert [entry["ok"] for entry in ledger] == [False, False, False, False, False, True]


def test_captions_2_fail_go_saves(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    def fail(*args):
        raise RuntimeError("no captions")
    monkeypatch.setattr(e, "yt_captions", fail)
    monkeypatch.setattr(e, "ytdlp_captions", fail)
    monkeypatch.setattr(e, "go_captions", lambda *args: ([{"start": 0, "end": 3, "text": "النص الثالث"}], "go"))
    attempts = []
    result = e.get_captions(VID, "ar", tmp_path / "subs", attempts)
    assert result[1] == "go"
    assert [a["ok"] for a in attempts] == [False, False, True]


def test_ffprobe_rejects_video_without_audio(tmp_path):
    only_video = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=64x64:r=2:d=2", "-an", "-c:v", "mpeg4", str(only_video)],
                   check=True, capture_output=True)
    e = core.Engine(tmp_path)
    with pytest.raises(ValueError, match="no actual audio"):
        e.check_audio(only_video)
    real = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", str(real)], check=True, capture_output=True)
    assert 1.9 < e.check_audio(real) < 2.1


def test_transcript_search_normalizes_arabic_and_provides_citation(tmp_path):
    e = core.Engine(tmp_path)
    store = core.JobStore(e)
    jobid = "a" * 32
    jobdir = store.base / jobid
    jobdir.mkdir()
    core.atomic_json(jobdir / "status.json", {"job_id": jobid, "state": "completed"})
    result = {"ok": True, **core.Result(VID, "asr:whisper.cpp", [
        {"start": 1.2, "end": 2.3, "text": "هذا إِسْنَادٌ صحيح"},
        {"start": 3.3, "end": 4.1, "text": "قال الامام البخاري"},
        {"start": 5.0, "end": 6.1, "text": "إسنادٌ آخر"}], "ar").to_dict()}
    core.atomic_json(jobdir / "result.json", result)
    found = store.search(jobid, "اسناد", max_matches=1)
    assert found["total_matches"] == 2
    assert found["truncated"] is True
    assert found["matches"][0]["segment_index"] == 0
    assert found["matches"][0]["youtube_url"].endswith("t=1s")
    with pytest.raises(ValueError):
        store.search(jobid, "")


def test_pending_job_queue_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "JOB_QUEUE_LIMIT", 1)
    e = core.Engine(tmp_path)
    gate = threading.Event()
    def slow_job(*args, **kwargs):
        gate.wait(timeout=2)
        return {"ok": True, **core.Result(VID, "mock", [], "ar").to_dict()}
    monkeypatch.setattr(e, "transcribe", slow_job)
    store = core.JobStore(e)
    first = store.submit(VID, mode="captions")
    with pytest.raises(RuntimeError, match="queue full"):
        store.submit(VID, mode="captions")
    gate.set()
    for _ in range(80):
        if store.get_status(first["job_id"])["state"] == "completed":
            break
        time.sleep(.025)
    assert store.get_status(first["job_id"])["state"] == "completed"
