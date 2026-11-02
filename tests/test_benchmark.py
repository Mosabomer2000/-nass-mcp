import pytest
from nass_mcp.benchmark import normalize, distance, score, aggregate


def test_arabic_policy_normalizes_diacritics_without_changing_original():
    raw = "إِنَّ ٱللَّهَ على كُلِّ شَيْءٍ قَدِيرٌ"
    assert normalize(raw, "arabic_basic") == "ان الله علي كل شيء قدير"
    assert "إ" in raw


def test_literal_policy_preserves_arabic_distinctions():
    assert normalize("إِله", "literal") != normalize("اله", "literal")


def test_simple_error_counts():
    r = score("السلام عليكم ورحمة الله", "السلام عليكم الله")
    assert r["word_errors"] == 1
    assert r["reference_words"] == 4
    assert r["wer"] == 0.25


def test_insertions_can_give_wer_over_one():
    result = score("مرحبا", "مرحبا مرحبا مرحبا")
    assert result["wer"] == 2.0


def test_empty_reference_rejected():
    with pytest.raises(ValueError):
        score("...?!", "الجواب")


def test_micro_wer_weighted_by_word_count():
    first = {"ok": True, "reference_quality": "human_verified",
             "metrics": score("one two three four five", "one two three four five", "literal")}
    second = {"ok": True, "reference_quality": "unverified",
              "metrics": score("الله", "رحمة")}
    r = aggregate([first, second])
    assert r["evaluated"] == 2
    assert r["human_verified_references"] == 1
    assert r["micro_wer"] == round(1 / 6, 5)
    assert r["human_verified_micro_wer"] == 0.0


def test_policy_rejects_undefined_normalization():
    with pytest.raises(ValueError):
        normalize("أهلا", "unknown")
