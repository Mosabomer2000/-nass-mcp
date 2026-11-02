"""Natural, continuous Arabic 30-minute file: true Whisper + MCP acceptance.

No reference WER claimed: the source does not ship a human-audited transcript.
Output contains only resource measurements, timings and source identifiers.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from nass_mcp.core import Engine, load_whisper_model
from nass_mcp.host_acceptance import run_acceptance
from nass_mcp.longform import plan_windows
from nass_mcp.media_integrity import media_sha256, require_matching_media
from nass_mcp.seam_review import seam_review_page
from nass_mcp.server import jobs


def detect_language(audio: Path, seconds: float = 90, offsets=(90, 660, 1250)) -> list[dict]:
    model = load_whisper_model(os.environ.get("NASS_WHISPER_MODEL", "small"),
                               os.environ.get("NASS_DEVICE", "cpu"),
                               os.environ.get("NASS_COMPUTE_TYPE", "int8"))
    samples = []
    with tempfile.TemporaryDirectory(prefix="nass-langdetect-") as td:
        for idx, start in enumerate(offsets):
            part = Path(td) / f"sample-{idx}.wav"
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                            "-ss", str(start), "-i", str(audio),
                            "-t", str(seconds), "-vn", "-ar", "16000",
                            "-ac", "1", "-c:a", "pcm_s16le", str(part)],
                           check=True, timeout=120, capture_output=True)
            hypothesis, info = model.transcribe(str(part), language=None,
                                               beam_size=1, vad_filter=True)
            # Iterator inference must be consumed to test audio decoding fully.
            recognized = list(hypothesis)
            samples.append({
                "start_seconds": start, "detected_language": str(info.language),
                "reported_language_probability": round(float(info.language_probability), 4),
                "recognized_segments": len(recognized),
            })
    return samples


async def main():
    media = Path(os.environ["NASS_MEDIA_DIR"])
    path = media / "commons-arabic-conversation-30m.flac"
    engine = Engine()
    duration = engine.check_audio(path)
    seconds = int(os.environ["NASS_ASR_CHUNK_SECONDS"])
    overlap = float(os.environ["NASS_ASR_OVERLAP_SECONDS"])
    windows = plan_windows(duration, seconds, overlap)
    if duration < 1795 or len(windows) < 4:
        raise RuntimeError("Test must use at least 30 min of natural audio")
    detected = detect_language(path)
    ar_count = sum(x["detected_language"] == "ar" for x in detected)
    output = {
        "test_source": "Wikimedia Commons self-licensed Arabic-speaking conversation",
        "source_page": ("https://commons.wikimedia.org/wiki/"
                        "File:ARABIC_SPEAKING_COMMUNITY_Conversation_hour.webm"),
        "author": "Sandra Hanbo", "license": "CC BY-SA 4.0",
        "source_duration_seconds": round(duration, 2),
        "window_seconds": seconds, "overlap_seconds": overlap,
        "planned_windows": len(windows),
        "source_language_detection": detected,
        "arabic_detected_in_majority_of_samples": ar_count >= 2,
        "human_verified_transcript_exists": False,
        "wer": None, "cer": None,
        "source_audio_sha256_bound": False,
        "audio_or_transcript_text_in_artifact": False,
    }
    # Proceed only on genuinely Arabic speech. A title alone is not evidence.
    if ar_count < 2:
        output.update({"passed": False,
                       "failure_class": "not_predominantly_arabic_in_sampled_windows"})
    else:
        accepted = await run_acceptance(local_file=path.name, language="ar",
                                        max_wait_seconds=1500)
        output.update(accepted)
        if output.get("mcp_job_completed"):
            result = json.loads(
                (jobs.base / output["job_id"] / "result.json").read_text("utf-8"))
            segments = result.get("segments", [])
            try:
                require_matching_media(result, media_sha256(path))
                output["source_audio_sha256_bound"] = True
            except ValueError:
                output["source_audio_sha256_bound"] = False
            review = seam_review_page(jobs, output["job_id"], count=20,
                                      include_text=False)
            output["seams"] = review.get("seam_count")
            output["seam_review_ready"] = bool(review.get("ok"))
            output["chronological"] = all(
                segments[i]["start"] <= segments[i+1]["start"]
                for i in range(len(segments)-1))
            output["recording_end_covered"] = bool(
                segments and segments[-1]["end"] > duration * 0.70)
            output["recognized_segments"] = len(segments)
            output["passed"] = bool(output.get("passed") and output["chronological"]
                                    and output["recording_end_covered"]
                                    and output["seam_review_ready"]
                                    and output["source_audio_sha256_bound"]
                                    and output["seams"] == len(windows)-1)
    report = Path("nass-natural-arabic-30min-evidence.json")
    report.write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output.get("passed"):
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
