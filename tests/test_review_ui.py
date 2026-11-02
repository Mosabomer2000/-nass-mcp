"""Offline Arabic review interface: injection and provenance regression tests."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nass_mcp.review_ui import render_review_html


def clips(identifier="seam-0000"):
    return [{"id": identifier, "kind": "decoder_seam",
             "start_seconds": 3.0, "end_seconds": 9.0,
             "clip_file": "clip_0001.wav"}]


def test_page_is_standalone_local_only_and_contains_no_transcripts():
    html = render_review_html(clips(), "a" * 64)
    assert html.count("<script>") == 1
    assert "clip_0001.wav" in html
    assert 'type="application/json"' in html
    assert "connect-src 'none'" in html
    assert 'type="checkbox"' not in html  # Script creates an unchecked box.
    assert 'checkbox.type = "checkbox"' in html
    assert 'reviewer_attestation: Boolean(accepted)' in html
    assert 'accepted ? "human_checked" : "pending"' in html
    assert "ASR_TRANSCRIPT_SHOULD_NEVER_APPEAR" not in html
    assert "https://" not in html and "http://" not in html


def test_user_supplied_identifiers_cannot_escape_json_script():
    attack = '</script><img src=x onerror=alert(1)>&'
    html = render_review_html(clips(attack), "b" * 64)
    assert attack not in html
    assert "<img" not in html
    assert "<script" in html
    assert r"\u003c/script\u003e" in html
    block = re.search(
        r'<script type="application/json" id="review-data">(.*?)</script>',
        html, flags=re.S)
    assert block is not None
    parsed = json.loads(block.group(1))
    assert parsed["rows"][0]["id"] == attack


@pytest.mark.parametrize("bad_file", ["../secret.wav", "https://bad.invalid/x.wav",
                                      "clip_<x>.wav", "clip_1.wav",
                                      "clip_00001.wav"])
def test_bad_media_filename_rejected(bad_file):
    rows = clips()
    rows[0]["clip_file"] = bad_file
    with pytest.raises(ValueError, match="filename"):
        render_review_html(rows, "a" * 64)


@pytest.mark.parametrize("bad_hash", ["a" * 63, "Z" * 64, "not a hash"])
def test_hash_validation(bad_hash):
    with pytest.raises(ValueError, match="SHA-256"):
        render_review_html(clips(), bad_hash)


def test_page_does_not_embed_reference_or_model_words():
    row = clips()[0]
    row["reference_text"] = "SECRET_HUMAN_REFERENCE"
    row["model_text"] = "SECRET_ASR_OUTPUT"
    html = render_review_html([row], "c" * 64)
    assert "SECRET_HUMAN_REFERENCE" not in html
    assert "SECRET_ASR_OUTPUT" not in html
