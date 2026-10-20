import json
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from nass_mcp import core

ID = "QxC5E44QoZY"


@pytest.mark.parametrize("given", [ID, "https://youtu.be/"+ID+"?t=18",
    "https://www.youtube.com/watch?v="+ID+"&list=abc",
    "https://m.youtube.com/shorts/"+ID,
    "https://www.youtube.com/embed/"+ID,
    "https://www.youtube.com/live/"+ID])
def test_video_id(given):
    assert core.get_video_id(given) == ID


@pytest.mark.parametrize("bad", [
    "http://127.0.0.1/"+ID,
    "https://youtube.com.evil.org/watch?v="+ID,
    "https://youtube.com@evil.org/watch?v="+ID,
    "file:///etc/passwd", "/tmp/local.wav", "https://youtube.com/watch?v=INVALID",
    "https://www.youtube.com/playlist?list="+ID,
])
def test_invalid_urls_rejected(bad):
    with pytest.raises(ValueError):
        core.get_video_id(bad)


def test_parse_captions():
    srt = "1\n00:00:00,000 --> 00:00:01,500\nأولًا\n\n2\n00:00:01,500 --> 00:00:03,000\nثانيًا\n"
    s = core.parse_srt(srt)
    assert len(s) == 2
    assert s[1]["start"] == 1.5
    assert "00:00:03,000" in core.srt_text(s)
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\n<b>السلام</b>\n\n00:00:01.500 --> 00:00:02.500\nالسلام\n\n00:00:02.500 --> 00:00:03.500\nعليكم"
    out = core.parse_vtt(vtt)
    assert len(out) == 2
    assert out[0]["text"] == "السلام"
    assert out[0]["end"] == 2.5
    data = {"events": [{"tStartMs": 2000, "dDurationMs": 500, "segs": [{"utf8": "مرحبا"}]}]}
    assert core.parse_json3(json.dumps(data))[0]["start"] == 2.0


def test_caption_failure_falls_back_to_audio(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(e, "get_captions", lambda *a: None)
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"mock")
    monkeypatch.setattr(e, "acquire_audio", lambda video, dest, attempts: (audio, "pytubefix"))
    monkeypatch.setattr(e, "speech_to_text", lambda audio, language, work, attempts:
                        ([{"start": 0, "end": 1, "text": "النص من الصوت"}], "whisper.cpp"))
    result = e.transcribe(ID, mode="auto")
    assert result["ok"]
    assert result["source"] == "asr:whisper.cpp"
    assert result["audio_source"] == "pytubefix"
    assert result["is_audio_asr"] is True


def test_audio_mode_does_not_use_captions(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    def captions_should_never_be_called(*args):
        raise AssertionError("mode=audio must bypass all captions")
    monkeypatch.setattr(e, "get_captions", captions_should_never_be_called)
    monkeypatch.setattr(e, "acquire_audio", lambda *args: (tmp_path / "fake", "yt-dlp/default"))
    monkeypatch.setattr(e, "speech_to_text", lambda *args:
                        ([{"start": 0, "end": 2, "text": "صوت فعلي"}], "faster-whisper"))
    result = e.transcribe(ID, mode="audio")
    assert result["ok"] and result["source"] == "asr:faster-whisper"


def test_audio_three_fallbacks(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    fails = []
    monkeypatch.setattr(e, "ytdlp_audio", lambda *args: (_ for _ in ()).throw(RuntimeError("Forbidden")))
    ok = tmp_path / "success.m4a"
    ok.write_bytes(b"mock")
    monkeypatch.setattr(e, "pytubefix_audio", lambda *args: ok)
    monkeypatch.setattr(e, "check_audio", lambda *args: 15.0)
    audio, method = e.acquire_audio(ID, tmp_path, fails)
    assert audio == ok and method == "pytubefix"
    assert [x["ok"] for x in fails] == [False, False, True]


def test_asr_fallback(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(e, "faster_whisper_asr", lambda *args: (_ for _ in ()).throw(RuntimeError("missing model")))
    monkeypatch.setattr(e, "whisper_cpp_asr", lambda *args: [{"start": 0, "end": 1, "text": "صحيح"}])
    monkeypatch.delenv("NASS_ALLOW_EXTERNAL_ASR", raising=False)
    attempts = []
    seg, provider = e.speech_to_text(tmp_path / "audio", "ar", tmp_path, attempts)
    assert provider == "whisper.cpp"
    assert [a["ok"] for a in attempts] == [False, True]


def test_verify_does_not_merge_different_sources(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    captions = ([{"start": 0, "end": 1, "text": "التعليق المكتوب"}], "captions:manual")
    monkeypatch.setattr(e, "get_captions", lambda *args: captions)
    monkeypatch.setattr(e, "acquire_audio", lambda *args: (tmp_path / "fake", "yt-dlp"))
    monkeypatch.setattr(e, "speech_to_text", lambda *args:
                        ([{"start": 0, "end": 1, "text": "ما قيل بالفعل"}], "whisper.cpp"))
    result = e.transcribe(ID, mode="verify")
    assert result["text"] == "ما قيل بالفعل"
    assert result["verification"]["captions_segments"][0]["text"] == "التعليق المكتوب"


def test_job_store_paging_and_export(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    def fake_transcribe(*args, **kwargs):
        segs = [{"start": i, "end": i+1, "text": "كلمة" + str(i)} for i in range(125)]
        return {"ok": True, **core.Result(ID, "asr:faster-whisper", segs, "ar").to_dict()}
    monkeypatch.setattr(e, "transcribe", fake_transcribe)
    store = core.JobStore(e)
    job = store.submit(ID, "ar", "audio")
    for _ in range(80):
        status = store.get_status(job["job_id"])
        if status["state"] == "completed":
            break
        time.sleep(0.025)
    assert status["state"] == "completed"
    part = store.read(job["job_id"], 0, 60)
    assert part["next_segment"] == 60
    assert part["total_segments"] == 125
    last = store.read(job["job_id"], 120, 60)
    assert last["next_segment"] is None
    exported = store.export(job["job_id"], "srt")
    assert exported["ok"]
    assert Path(exported["file_on_server"]).is_file()


def test_restrict_local_file_to_intake(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    outside = tmp_path / "secret.mp3"
    outside.write_bytes(b"sensitive")
    monkeypatch.setattr(core, "MEDIA_ROOT", media)
    with pytest.raises(ValueError):
        core.safe_input_audio("../secret.mp3")
    (media / "link.mp3").symlink_to(outside)
    with pytest.raises(ValueError):
        core.safe_input_audio("link.mp3")
    (media / "ok.mp3").write_bytes(b"audio")
    assert core.safe_input_audio("ok.mp3").name == "ok.mp3"


def test_audio_download_job_reports_source_and_failures(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    media = tmp_path / 'actual.m4a'
    media.write_bytes(b'fake test fixture')
    def provider(_id, _where, attempts):
        attempts.append({'stage': 'audio', 'provider': 'yt-dlp/default', 'ok': False, 'message': 'blocked'})
        attempts.append({'stage': 'audio', 'provider': 'pytubefix', 'ok': True})
        return media, 'pytubefix'
    monkeypatch.setattr(e, 'acquire_audio', provider)
    monkeypatch.setattr(e, 'check_audio', lambda audio: 3.2)
    store = core.JobStore(e)
    job = store.submit_audio_download(ID)
    for _ in range(80):
        status = store.get_status(job['job_id'])
        if status['state'] == 'completed':
            break
        time.sleep(0.025)
    result = store.read(job['job_id'])
    assert result['source'] == 'raw_audio:pytubefix'
    assert result['file_on_server'].endswith('.m4a')
    assert result['attempts'][0]['ok'] is False


def test_audio_download_failure_retains_attempt_ledger(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    def provider(_id, _where, attempts):
        attempts.append({'stage': 'audio', 'provider': 'yt-dlp/default', 'ok': False})
        raise RuntimeError('all failed')
    monkeypatch.setattr(e, 'acquire_audio', provider)
    store = core.JobStore(e)
    job = store.submit_audio_download(ID)
    for _ in range(80):
        status = store.get_status(job['job_id'])
        if status['state'] == 'failed':
            break
        time.sleep(0.025)
    result = store.read(job['job_id'])
    assert result['ok'] is False
    assert result['attempts'][0]['provider'] == 'yt-dlp/default'


def test_audio_cache_survives_upstream_outage(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    original = tmp_path / 'real.m4a'
    original.write_bytes(b'cached fixture audio')
    monkeypatch.setattr(e, 'check_audio', lambda *a: 1.5)
    monkeypatch.setattr(e, 'ytdlp_audio', lambda *a: original)
    monkeypatch.setenv('NASS_AUDIO_CACHE', '1')
    a = []
    e.acquire_audio(ID, tmp_path / 'first', a)
    assert a[0]['provider'] == 'yt-dlp/default'
    def upstream_down(*args):
        raise RuntimeError('network down')
    monkeypatch.setattr(e, 'ytdlp_audio', upstream_down)
    monkeypatch.setattr(e, 'pytubefix_audio', upstream_down)
    b = []
    recovered, source = e.acquire_audio(ID, tmp_path / 'second', b)
    assert source == 'local-audio-cache' and recovered.read_bytes() == original.read_bytes()
    assert b[0]['ok'] is True


def test_caption_cache_survives_provider_outage(tmp_path, monkeypatch):
    e = core.Engine(tmp_path)
    monkeypatch.setattr(e, 'yt_captions', lambda *_: ([{'start': 0, 'end': 2, 'text': 'من الكاش'}], 'manual'))
    attempts = []
    result = e.get_captions(ID, 'ar', tmp_path, attempts)
    assert result[1] == 'manual'
    def offline(*args):
        raise RuntimeError('offline')
    monkeypatch.setattr(e, 'yt_captions', offline)
    monkeypatch.setattr(e, 'ytdlp_captions', offline)
    attempts = []
    result = e.get_captions(ID, 'ar', tmp_path, attempts)
    assert result[1] == 'cache:manual'
    assert attempts[0]['provider'] == 'local-captions-cache'


def test_clip_is_real_audio_using_ffmpeg(tmp_path, monkeypatch):
    import subprocess
    import wave
    media = tmp_path / 'input'
    media.mkdir()
    source = media / 'example.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=3', '-ar', '16000', '-ac', '1', '-y', str(source)],
                   check=True)
    monkeypatch.setattr(core, 'MEDIA_ROOT', media)
    e = core.Engine(tmp_path / 'data')
    def fake_asr(*args):
        return ([{'start': 0, 'end': 3, 'text': 'synthetic fixture'}], 'faster-whisper')
    monkeypatch.setattr(e, 'speech_to_text', fake_asr)
    store = core.JobStore(e)
    job = store.submit('example.wav', 'ar', 'audio', local=True)
    for _ in range(80):
        status = store.get_status(job['job_id'])
        if status['state'] == 'completed':
            break
        time.sleep(0.025)
    assert status['state'] == 'completed'
    excerpt = store.make_audio_clip(job['job_id'], 0.5, 1.5)
    assert excerpt.exists() and excerpt.stat().st_size > 100
    assert 1.3 < e.check_audio(excerpt) < 1.7
    with pytest.raises(ValueError):
        store.make_audio_clip(job['job_id'], 1, 46)
