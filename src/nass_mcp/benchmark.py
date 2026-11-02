"""Transparent Arabic/English ASR evaluation metrics for source-grounded benchmarks.

Only human-verified references are labelled verified. This module never
produces fabricated accuracy from confidence proxies or unverified captions.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter


def normalize(text: str, policy: str = "literal") -> str:
    """Return a repeatable comparison string; the original transcript remains untouched."""
    if not isinstance(text, str):
        raise TypeError("Transcript must be text")
    if policy not in ("literal", "arabic_basic"):
        raise ValueError("Policy must be literal or arabic_basic")
    text = unicodedata.normalize("NFKC", text)
    if policy == "arabic_basic":
        text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
        text = re.sub(r"[\u0622\u0623\u0625\u0671]", "\u0627", text)
        text = text.replace("\u0649", "\u064a")
    clean = []
    for char in text.casefold():
        category = unicodedata.category(char)
        if category[0] in ("L", "N") or category in ("Mn", "Mc"):
            clean.append(char)
        elif char.isspace() or category[0] in ("P", "S", "C"):
            clean.append(" ")
        else:
            clean.append(" ")
    return " ".join("".join(clean).split())


def distance(a: list[str] | str, b: list[str] | str) -> int:
    """Levenshtein substitutions + deletions + insertions, 2-row space."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1,
                           prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def score(reference: str, prediction: str, policy: str = "arabic_basic") -> dict:
    reference_normalized = normalize(reference, policy)
    prediction_normalized = normalize(prediction, policy)
    ref_words = reference_normalized.split()
    pred_words = prediction_normalized.split()
    if not ref_words:
        raise ValueError("Reference transcript has zero comparable words")
    word_errors = distance(ref_words, pred_words)
    char_errors = distance(reference_normalized.replace(" ", ""),
                           prediction_normalized.replace(" ", ""))
    char_count = len(reference_normalized.replace(" ", ""))
    if not char_count:
        raise ValueError("Reference transcript has zero comparable characters")
    return {
        "policy": policy, "reference_words": len(ref_words),
        "prediction_words": len(pred_words),
        "word_errors": word_errors,
        "wer": round(word_errors / len(ref_words), 5),
        "reference_characters": char_count,
        "character_errors": char_errors,
        "cer": round(char_errors / char_count, 5),
    }


def aggregate(rows: list[dict]) -> dict:
    """Micro-averaged errors. No weighted-average-of-rounded-WER mistakes."""
    valid = [r for r in rows if r.get("ok") is True and "metrics" in r]
    total = Counter()
    for item in valid:
        metrics = item["metrics"]
        for key in ("word_errors", "reference_words", "character_errors",
                    "reference_characters"):
            total[key] += metrics[key]
    verified = [item for item in valid if item.get("reference_quality") == "human_verified"]
    ans = {
        "evaluated": len(valid),
        "human_verified_references": len(verified),
        "reference_word_count": total["reference_words"],
        "micro_wer": (round(total["word_errors"] / total["reference_words"], 5)
                       if total["reference_words"] else None),
        "micro_cer": (round(total["character_errors"] / total["reference_characters"], 5)
                       if total["reference_characters"] else None),
        "warning": "Corpus scores are not statistically representative without a declared sampling and annotation methodology.",
    }
    verified_words = sum(row["metrics"]["reference_words"] for row in verified)
    verified_chars = sum(row["metrics"]["reference_characters"] for row in verified)
    ans["human_verified_micro_wer"] = (
        round(sum(row["metrics"]["word_errors"] for row in verified) / verified_words, 5)
        if verified_words else None)
    ans["human_verified_micro_cer"] = (
        round(sum(row["metrics"]["character_errors"] for row in verified) / verified_chars, 5)
        if verified_chars else None)
    return ans
