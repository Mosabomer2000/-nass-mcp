"""Real FFmpeg acceptance for private human-review clip export."""
from __future__ import annotations

import json
import subprocess

import pytest

from scripts.export_review_clips import export_review_clips, prepare_intervals

DIGEST = "a" * 64


def asr_result():
    return {
        "is_audio_asr": True, "source": "asr:faster-whisper",
        "recognition": {"duration_seconds": 8, "audio_sha256": DIGEST},
        "segments": [{"start": 1, "end": 3, "text": "هذا النص سري"}],
    }


def row(identifier, begin, end, digest=DIGEST, kind="decoder_seam"):
    return {
        "id": identifier, "kind": kind, "start_seconds": begin,
        "end_seconds": end, "audio_sha256": digest,
        "reference_text": "هذه كلمات خاصة لمراجع بشري",
        "review_state": "human_checked", "reviewer_attestation": True,
    }


def test_clip_plan_rejects_unbound_or_overlapping_intervals():
    with pytest.raises(ValueError, match="SHA256"):
        prepare_intervals(asr_result(), [row("one", 1, 3, "b" * 64)], DIGEST, 8)
    with pytest.raises(ValueError, match="overlap"):
        prepare_intervals(asr_result(), [row("one", 1, 3),
                                        row("two", 2, 4)], DIGEST, 8)
    with pytest.raises(ValueError, match="duplicate"):
        prepare_intervals(asr_result(), [row("same", 1, 3),
                                        row("same", 4, 6)], DIGEST, 8)
    with pytest.raises(ValueError, match="shorter"):
        prepare_intervals(asr_result(), [row("one", 1, 3)], DIGEST, 7.0)


@pytest.mark.parametrize("bad_interval", [
    (float("nan"), 4), (0, float("inf")), (3, 2), (-1, 2), (1, 12),
    (True, 2),
])
def test_clip_plan_rejects_bad_coordinates(bad_interval):
    with pytest.raises(ValueError):
        prepare_intervals(asr_result(),
                          [row("bad", *bad_interval)], DIGEST, 8)


def test_clip_export_is_private_and_contains_no_transcript(tmp_path):
    from nass_mcp.manual_review import file_digest
    audio = tmp_path / "original.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=500:duration=8", "-ac", "1", "-ar",
         "16000", str(audio)],
        check=True, timeout=30)
    digest = file_digest(audio)
    manifest = [
        row("seam-1", 1, 3, digest),
        row("control-1", 5, 7, digest, "interior_control"),
    ]
    output = tmp_path / "private-clips"
    result = asr_result()
    result["recognition"]["audio_sha256"] = digest
    report = export_review_clips(audio, result, manifest, output)
    assert report["clip_count"] == 2
    assert not report["human_review_completed"]
    assert (output / "clip_0001.wav").stat().st_size > 100
    assert (output / "clip_0002.wav").stat().st_size > 100
    index = (output / "index.json").read_text("utf-8")
    assert "هذا النص سري" not in index
    assert "هذه كلمات خاصة" not in index
    assert "reference_text" not in index
    parsed = json.loads(index)
    assert parsed["machine_transcript_included"] is False
    assert parsed["reference_transcript_included"] is False
    private_page = output / "review.html"
    assert private_page.is_file()
    html = private_page.read_text("utf-8")
    assert "clip_0001.wav" in html and "clip_0002.wav" in html
    assert "هذا النص سري" not in html
    assert "هذه كلمات خاصة" not in html
    assert "connect-src 'none'" in html
    assert report["review_page"] == str(private_page.resolve())
    with pytest.raises(FileExistsError):
        export_review_clips(audio, result, manifest, output)


def test_clip_export_refuses_tampered_audio_manifest_without_creating_output(tmp_path):
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"not the audited audio")
    output = tmp_path / "clips"
    # Fake/non-audio is rejected by ffprobe before any output folder is made.
    with pytest.raises(Exception):
        export_review_clips(audio, asr_result(), [row("one", 1, 2)], output)
    assert not output.exists()


def test_clip_planner_requires_provenance_match():
    item = asr_result()
    item["recognition"]["audio_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="mismatch"):
        prepare_intervals(item, [row("one", 1, 3)], DIGEST, 8)
    del item["recognition"]["audio_sha256"]
    with pytest.raises(ValueError, match="re-transcribe"):
        prepare_intervals(item, [row("one", 1, 3)], DIGEST, 8)
