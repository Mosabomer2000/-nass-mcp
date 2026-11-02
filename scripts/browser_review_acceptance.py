"""Actual Chromium smoke test for the offline Nass review workflow.

Optional developer tool (Playwright is not a runtime dependency):
    pip install playwright
    python scripts/browser_review_acceptance.py

The test creates synthetic tone clips, never downloads voice recordings,
and does not send text or media to a network service.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import tempfile
import wave
from pathlib import Path

from nass_mcp.review_ui import render_review_html


def synthetic_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"".join(
            struct.pack("<h", int(4000 * math.sin(2 * math.pi * 440 * i / 16000)))
            for i in range(16000)
        ))


def run_acceptance() -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install optional browser-test package: pip install playwright") from exc

    binary = next((shutil.which(name) for name in
                   ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
                   if shutil.which(name)), None)
    if not binary:
        raise RuntimeError("Install local Chrome/Chromium for the browser smoke test")

    with tempfile.TemporaryDirectory(prefix="nass-review-browser-") as root:
        folder = Path(root)
        clips = [folder / f"clip_{i:04d}.wav" for i in (1, 2)]
        for clip in clips:
            synthetic_wav(clip)
        digest = hashlib.sha256(b"private-fixture-identity").hexdigest()
        rows = [
            {"id": "seam-001", "kind": "decoder_seam",
             "start_seconds": 1.0, "end_seconds": 2.0,
             "clip_file": "clip_0001.wav"},
            {"id": "control-001", "kind": "interior_control",
             "start_seconds": 3.0, "end_seconds": 4.0,
             "clip_file": "clip_0002.wav"},
        ]
        html = folder / "review.html"
        html.write_text(render_review_html(rows, digest), encoding="utf-8")
        errors = []
        remote_requests = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=binary, headless=True,
                                         args=["--no-sandbox", "--disable-gpu"])
            try:
                page = browser.new_page(accept_downloads=True)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("request", lambda request:
                        remote_requests.append(request.url)
                        if request.url.startswith(("http://", "https://")) else None)
                page.goto(html.as_uri())
                assert page.locator("audio").count() == 2
                assert page.locator("textarea").count() == 2
                assert "0 / 2" in page.locator("#progress").inner_text()
                ready = page.locator("audio").first.evaluate("""audio => new Promise(resolve => {
                    if (audio.readyState >= 1) return resolve(true);
                    audio.onloadedmetadata = () => resolve(true);
                    audio.onerror = () => resolve(false);
                    audio.load();
                })""")
                assert ready, "The browser could not decode the sibling WAV clip"

                page.locator("textarea").first.fill("تجربة مراجعة بشرية")
                page.locator('input[type="checkbox"]').first.check()
                assert "1 / 2" in page.locator("#progress").inner_text()
                with page.expect_download() as captured:
                    page.locator("#export").click()
                download = captured.value
                assert download.suggested_filename == "nass-reviewed.jsonl"
                exported = Path(download.path()).read_text(encoding="utf-8")
                entries = [json.loads(line) for line in exported.splitlines() if line.strip()]
                assert len(entries) == 2
                assert entries[0]["review_state"] == "human_checked"
                assert entries[0]["reviewer_attestation"] is True
                assert entries[1]["review_state"] == "pending"
                assert entries[1]["reviewer_attestation"] is False

                page.reload()
                assert page.locator("textarea").first.input_value() == ""
                page.locator("#import-file").set_input_files({
                    "name": "review.jsonl",
                    "mimeType": "application/x-ndjson",
                    "buffer": exported.encode("utf-8"),
                })
                assert page.locator("textarea").first.input_value() == "تجربة مراجعة بشرية"
                assert page.locator('input[type="checkbox"]').first.is_checked()
                assert "استُعيدت 2" in page.locator("#import-status").inner_text()

                # A malicious/different session cannot overwrite valid corrections.
                changed = exported.replace(digest, "a" * 64 if digest != "a" * 64 else "b" * 64)
                page.locator("#import-file").set_input_files({
                    "name": "wrong-audio.jsonl",
                    "mimeType": "application/x-ndjson",
                    "buffer": changed.encode("utf-8"),
                })
                assert "لم يُستورد" in page.locator("#import-status").inner_text()
                assert page.locator("textarea").first.input_value() == "تجربة مراجعة بشرية"
                assert not errors, "Browser JavaScript errors: " + "; ".join(errors)
                assert not remote_requests, "Offline page issued remote HTTP requests"
            finally:
                browser.close()
    return {
        "ok": True, "browser": Path(binary).name,
        "media_decoding": True, "export_attestation": True,
        "resume_checked": True, "mismatch_rejected_without_data_loss": True,
        "external_network_requests": 0,
        "source": "synthetic tones only", "real_human_accuracy_verified": False,
    }


if __name__ == "__main__":
    print(json.dumps(run_acceptance(), ensure_ascii=False, indent=2))
