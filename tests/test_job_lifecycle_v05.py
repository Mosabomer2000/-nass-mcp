"""Concurrency, durable state and queued-cancellation regression tests."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from nass_mcp import core

VID = "QxC5E44QoZY"


def wait_for(store, jobid, expected, timeout=5):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        state = store.get_status(jobid)["state"]
        if state == expected:
            return state
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach {expected}: {state}")


def test_atomic_json_survives_simultaneous_replacements(tmp_path):
    target = tmp_path / "same.json"
    original = {"index": -1, "body": "ابتدائي" * 5000}
    core.atomic_json(target, original)
    gate = threading.Barrier(8)

    def write(i):
        gate.wait(timeout=5)
        core.atomic_json(target, {"index": i, "body": ("اختبار" + str(i)) * 2500})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(8)))
    saved = json.loads(target.read_text("utf-8"))
    assert saved["index"] in range(8)
    assert saved["body"] == ("اختبار" + str(saved["index"])) * 2500
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_json_old_value_survives_serialization_failure(tmp_path):
    target = tmp_path / "result.json"
    core.atomic_json(target, {"ok": True})
    with pytest.raises(TypeError):
        core.atomic_json(target, {"bad": object()})
    assert json.loads(target.read_text("utf-8")) == {"ok": True}
    assert list(tmp_path.iterdir()) == [target]


def test_cancel_queued_job_without_affecting_running_job(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    engine = core.Engine(tmp_path)
    monkeypatch.setenv("NASS_WORKERS", "1")

    def fake_transcribe(*args, **kwargs):
        started.set()
        assert release.wait(5), "Blocked fake worker was not released"
        return {"ok": True, **core.Result(
            VID, "asr:fixture", [{"start": 0, "end": 1, "text": "تم"}], "ar").to_dict()}

    monkeypatch.setattr(engine, "transcribe", fake_transcribe)
    store = core.JobStore(engine)
    try:
        first = store.submit(VID, "ar", "audio")
        assert started.wait(2)
        assert wait_for(store, first["job_id"], "running") == "running"
        second = store.submit(VID, "ar", "audio")
        response = store.cancel(second["job_id"])
        assert response == {"job_id": second["job_id"], "cancelled": True, "state": "cancelled"}
        assert store.get_status(second["job_id"])["state"] == "cancelled"
        assert not (store.base / second["job_id"] / "result.json").exists()
        assert store.cancel(first["job_id"])["cancelled"] is False
        release.set()
        assert wait_for(store, first["job_id"], "completed") == "completed"
        assert store.cancel(first["job_id"])["cancelled"] is False
        assert len(store._jobs) == 0
        assert len(store._futures) == 0
        assert store.get_status(second["job_id"])["state"] == "cancelled"
    finally:
        release.set()
        store._pool.shutdown(wait=True)


def test_restart_returns_completed_and_cancelled_history(tmp_path, monkeypatch):
    engine = core.Engine(tmp_path)
    monkeypatch.setenv("NASS_WORKERS", "1")
    started, release = threading.Event(), threading.Event()

    def fake_transcribe(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return {"ok": True, **core.Result(
            VID, "asr:fixture", [{"start": 0, "end": 1, "text": "تم"}], "ar").to_dict()}

    monkeypatch.setattr(engine, "transcribe", fake_transcribe)
    s = core.JobStore(engine)
    try:
        running = s.submit(VID)
        assert started.wait(2)
        queued = s.submit(VID)
        s.cancel(queued["job_id"])
        release.set()
        wait_for(s, running["job_id"], "completed")
    finally:
        release.set()
        s._pool.shutdown(wait=True)
    s2 = core.JobStore(engine)
    try:
        assert s2.get_status(running["job_id"])["state"] == "completed"
        assert s2.get_status(queued["job_id"])["state"] == "cancelled"
    finally:
        s2._pool.shutdown(wait=True)


def test_cancel_rejects_invalid_identifier(tmp_path):
    store = core.JobStore(core.Engine(tmp_path))
    try:
        with pytest.raises(ValueError):
            store.cancel("../escape")
    finally:
        store._pool.shutdown(wait=True)
