"""Source-grounded, paginated seam review. No fabricated confidence scores."""
import json
import pytest

from nass_mcp.seam_review import seam_review_page

JOB = "b" * 32


class Store:
    def __init__(self, root, result):
        self.base = root / "jobs"
        target = self.base / JOB
        target.mkdir(parents=True)
        (target / "result.json").write_text(json.dumps(result, ensure_ascii=False), "utf-8")

    def get_status(self, job_id):
        if job_id != JOB:
            raise ValueError("Unknown job")
        return {"state": "completed"}


def result(duration=66, chunk=20, overlap=4):
    return {
        "ok": True, "source": "asr:faster-whisper", "is_audio_asr": True,
        "recognition": {"backend": "faster-whisper",
                        "duration_seconds": duration,
                        "configured_chunk_seconds": chunk,
                        "configured_overlap_seconds": overlap},
        "segments": [{"start": 16.4, "end": 18.2, "text": "كلام قبل الوصل"},
                     {"start": 18.7, "end": 21.2, "text": "كلام بعد الوصل"},
                     {"start": 32.3, "end": 33.7, "text": "مقطع لاحق"}],
    }


def test_seam_count_paging_and_audio_excerpt_positions(tmp_path):
    store = Store(tmp_path, result())
    x = seam_review_page(store, JOB, start_seam=0, count=1, context_seconds=4)
    assert x["ok"] and x["seam_count"] > 1
    assert x["next_seam"] == 1
    assert x["seams"][0]["seam_seconds"] == 18
    assert x["seams"][0]["listen_from_seconds"] == 14
    assert x["seams"][0]["listen_until_seconds"] == 22
    assert len(x["seams"][0]["segments_near_seam"]) == 2
    assert x["accuracy_verified"] is False
    y = seam_review_page(store, JOB, start_seam=1, count=20)
    assert y["next_seam"] is None
    assert len(x["seams"]) + len(y["seams"]) == x["seam_count"]


def test_hide_transcript_words_for_ci_reports(tmp_path):
    store = Store(tmp_path, result())
    text = json.dumps(seam_review_page(store, JOB, count=1, include_text=False), ensure_ascii=False)
    assert "كلام" not in text
    assert '"text"' not in text


def test_source_without_asr_does_not_claim_seams(tmp_path):
    r = result()
    r["is_audio_asr"] = False
    store = Store(tmp_path, r)
    assert seam_review_page(store, JOB)["ok"] is False


def test_unrecorded_duration_is_not_inferred(tmp_path):
    r = result()
    del r["recognition"]["duration_seconds"]
    store = Store(tmp_path, r)
    assert "duration" in seam_review_page(store, JOB)["error"].lower()


def test_single_pass_has_no_chunk_seams(tmp_path):
    store = Store(tmp_path, result(chunk=0))
    out = seam_review_page(store, JOB)
    assert out["seam_count"] == 0 and not out["seams"]


@pytest.mark.parametrize("kwargs", [
    {"start_seam": -1}, {"start_seam": True}, {"count": 0},
    {"count": 21}, {"context_seconds": 0},
    {"context_seconds": float("nan")}, {"context_seconds": 25},
    {"include_text": "false"},
])
def test_invalid_pagination_or_context_rejected(tmp_path, kwargs):
    store = Store(tmp_path, result())
    with pytest.raises(ValueError):
        seam_review_page(store, JOB, **kwargs)
