"""Nass diagnostic taxonomy: preserve source evidence, never echo secrets."""
import json
import time
from nass_mcp.failure_analysis import classify_failure, diagnose_attempts
from nass_mcp.core import Engine, JobStore, atomic_json


def test_youtube_login_wall_is_not_misreported_as_missing_captions():
    c = classify_failure("DownloadError: Sign in to confirm you're not a bot")
    assert c["category"] == "youtube_access_challenge"


def test_http_403_is_not_claimed_to_be_a_pot_failure():
    assert classify_failure("HTTP Error 403: Forbidden")["category"] == "http_forbidden"


def test_missing_binary_is_not_network_failure():
    assert classify_failure("Optional yt-transcript Go command is not installed")["category"] == "dependency_unavailable"


def test_attempts_do_not_echo_access_tokens():
    secret = "x-supersecret-123"
    result = diagnose_attempts([{"stage": "audio", "provider": "yt-dlp/default",
                                 "ok": False, "message": "HTTP 403 " + secret}])
    assert secret not in json.dumps(result)
    assert result["categories"]["http_forbidden"] == 1


def test_multi_error_summary_does_not_infer_unobserved_success():
    d = diagnose_attempts([{"stage": "captions", "provider": "api", "ok": False,
                            "message": "RequestBlocked"},
                           {"stage": "audio", "provider": "yt-dlp", "ok": False,
                            "message": "Sign in to confirm you're not a bot"}])
    assert d["categories"]["youtube_access_challenge"] == 2
    assert not any(x["success"] for x in d["attempts"])


def test_job_diagnosis_for_persisted_failure(tmp_path):
    engine = Engine(tmp_path)
    store = JobStore(engine)
    jobid = "a" * 32
    target = tmp_path / "jobs" / jobid
    target.mkdir(parents=True)
    atomic_json(target / "status.json", {"job_id": jobid, "state": "failed",
                "attempts": [{"stage": "captions", "provider": "yt-dlp", "ok": False,
                              "message": "RequestBlocked"}]})
    d = store.diagnose(jobid)
    assert d["job_id"] == jobid
    assert d["categories"]["youtube_access_challenge"] == 1
