"""Tests distinguish lifetime peak RAM from per-job consumption."""
from nass_mcp.runtime_resources import resource_delta, snapshot_process


def test_resource_snapshot_does_not_contain_secrets():
    sample = snapshot_process()
    if sample is not None:
        assert sample["process_peak_rss_mb"] >= 0
        assert sample["total_user_cpu_seconds"] >= 0
        assert all("token" not in field.lower() for field in sample)


def test_resource_diff_reports_honest_semantics():
    before = {"platform": "linux", "process_peak_rss_mb": 100.0,
              "terminated_child_max_peak_rss_mb": 2.0,
              "total_user_cpu_seconds": 5.0, "total_system_cpu_seconds": 1.0}
    after = {"platform": "linux", "process_peak_rss_mb": 130.0,
             "terminated_child_max_peak_rss_mb": 40.0,
             "total_user_cpu_seconds": 8.12, "total_system_cpu_seconds": 1.25}
    profile = resource_delta(before, after)
    assert profile["available"] is True
    assert profile["process_peak_rss_mb_since_process_start"] == 130.0
    assert profile["terminated_child_max_peak_rss_mb_since_process_start"] == 40.0
    assert profile["user_cpu_seconds_during_test"] == 3.12
    assert "not per-job" in profile["interpretation"]
    assert "VRAM" in profile["interpretation"]


def test_unsupported_system_returns_no_estimates():
    assert resource_delta(None, None)["available"] is False
