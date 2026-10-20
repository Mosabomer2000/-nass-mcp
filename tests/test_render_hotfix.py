"""Regression checks for packaged Node runtime / fallback ordering."""
from pathlib import Path
import subprocess
import pytest
from nass_mcp import core, __version__


def test_docker_installs_js_dependencies_in_installed_package():
    source = (Path(__file__).parents[1] / "Dockerfile").read_text()
    assert 'python -c \'from pathlib import Path; import nass_mcp;' in source
    assert 'npm install --prefix "$NODE_DIR"' in source
    assert 'test -d "$NODE_DIR/node_modules/youtubei.js"' in source
    assert 'npm install --prefix /app/src/nass_mcp/_node' not in source


def test_health_version_matches_package_version():
    assert core.health()["version"] == __version__


def test_js_reports_missing_dependency_without_leaking_stderr(tmp_path, monkeypatch):
    engine = core.Engine(tmp_path / "engine")
    monkeypatch.setattr(core.shutil, "which", lambda command: "/usr/bin/node")
    secret = "PRIVATE_SIGNED_MEDIA_URL_SECRET"
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr=("ERR_MODULE_NOT_FOUND " + secret).encode())
    monkeypatch.setattr(core.subprocess, "run", failed)
    with pytest.raises(RuntimeError, match="dependency missing") as exc:
        engine.youtubejs_audio("QxC5E44QoZY", tmp_path / "out")
    assert secret not in str(exc.value)


def test_ytdlp_embedded_client_is_independent_attempt(tmp_path, monkeypatch):
    eng = core.Engine(tmp_path / "engine")
    monkeypatch.setenv("NASS_AUDIO_CACHE", "0")
    called = []
    def media(vid, dest, client):
        called.append(client)
        if client != "web_embedded":
            raise RuntimeError("upstream denied")
        path = tmp_path / "sample.m4a"
        path.write_bytes(b"local test bytes")
        return path
    monkeypatch.setattr(eng, "ytdlp_audio", media)
    monkeypatch.setattr(eng, "check_audio", lambda *_: 3.0)
    log = []
    audio, provider = eng.acquire_audio("QxC5E44QoZY", tmp_path / "job", log)
    assert provider == "yt-dlp/web_embedded"
    assert called == ["default", "ios", "web_embedded"]
    assert [event["ok"] for event in log] == [False, False, True]
