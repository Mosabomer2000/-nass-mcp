"""User-attested review only; never score unverifiable or partial intervals."""
from __future__ import annotations
import pytest

from nass_mcp.manual_review import review_template, evaluate_reviews, file_digest

DIGEST = "a"*64


def result():
    return {"ok": True, "is_audio_asr": True, "source": "asr:faster-whisper",
            "recognition": {"backend": "faster-whisper", "model": "small",
                            "configured_chunk_seconds": 20,
                            "configured_overlap_seconds": 4,
                            "duration_seconds": 42},
            "segments": [{"start": 12, "end": 18, "text": "العلم النافع"},
                         {"start": 18, "end": 23, "text": "العمل الصالح"},
                         {"start": 32, "end": 38, "text": "الصدق"}]}


def test_seam_review_template_no_claim_of_human_accuracy():
    rows = review_template(result(), DIGEST, context_seconds=4)
    assert len(rows) == 2
    assert rows[0]["review_state"] == "pending"
    assert rows[0]["reference_text"] == ""
    assert rows[0]["audio_sha256"] == DIGEST
    assert rows[0]["start_seconds"] <= 12
    assert rows[0]["end_seconds"] >= 23


def test_unreviewed_rows_are_excluded():
    rows = review_template(result(), DIGEST)
    report = evaluate_reviews(result(), rows, DIGEST)
    assert report["scored_rows"] == 0
    assert report["aggregate"]["micro_wer"] is None
    assert report["full_recording_wer"] is None


def test_valid_manually_attested_sample_scores_exact_match():
    row = {"id": "human-1", "start_seconds": 12, "end_seconds": 23,
           "audio_sha256": DIGEST, "reference_text": "العلم النافع العمل الصالح",
           "review_state": "human_checked", "reviewer_attestation": True}
    report = evaluate_reviews(result(), [row], DIGEST)
    assert report["scored_rows"] == 1
    assert report["aggregate"]["human_verified_micro_wer"] == 0


def test_segment_crossing_boundary_cannot_be_scored():
    row = {"id": "bad-cut", "start_seconds": 13, "end_seconds": 22,
           "audio_sha256": DIGEST, "reference_text": "العلم النافع العمل الصالح",
           "review_state": "human_checked", "reviewer_attestation": True}
    report = evaluate_reviews(result(), [row], DIGEST)
    assert report["scored_rows"] == 0
    assert report["excluded_rows"][0]["reason"] == "segment_crosses_review_boundary"


def test_sha_mismatch_rejected_even_if_human_attested():
    row = {"id": "bad-audio", "start_seconds": 12, "end_seconds": 23,
           "audio_sha256": "b"*64, "reference_text": "العلم",
           "review_state": "human_checked", "reviewer_attestation": True}
    with pytest.raises(ValueError, match="different audio"):
        evaluate_reviews(result(), [row], DIGEST)


def test_overlap_rejected_and_does_not_double_count_words():
    rows = [
        {"id": "a", "start_seconds": 10, "end_seconds": 23,
         "audio_sha256": DIGEST, "reference_text": "العلم النافع العمل الصالح",
         "review_state": "human_checked", "reviewer_attestation": True},
        {"id": "b", "start_seconds": 19, "end_seconds": 35,
         "audio_sha256": DIGEST, "reference_text": "الصدق",
         "review_state": "human_checked", "reviewer_attestation": True},
    ]
    with pytest.raises(ValueError, match="overlap"):
        evaluate_reviews(result(), rows, DIGEST)


def test_actual_file_sha256(tmp_path):
    media = tmp_path / "arabic.wav"
    media.write_bytes(b"Test bytes, not actually a source recording")
    assert len(file_digest(media)) == 64
