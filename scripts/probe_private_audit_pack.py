"""In-CI inspection of a PRIVATE full audio-review pack, without uploading clips.

Verifies a real source-bound ASR result can produce reviewable local WAVs.
The pack and the annotation JSONL exist only in a TemporaryDirectory, and
the returned summary contains NO recognized words, reference words or paths.

A passing probe does not mean any human has listened to the clips.
"""
from __future__ import annotations

import json
import tempfile
import wave
from pathlib import Path

from nass_mcp.manual_review import evaluate_reviews, file_digest
from scripts.prepare_human_audit import prepare_audit


def probe_private_pack(audio: Path, result: dict, *,
                       context_seconds: float = 8.0,
                       controls: int = 8) -> dict:
    """Validate actual output files and return only disclosure-safe numbers."""
    with tempfile.TemporaryDirectory(prefix="nass-private-review-") as tmp:
        directory = Path(tmp) / "pack"
        prepared = prepare_audit(
            audio, result, directory,
            context_seconds=context_seconds, control_intervals=controls,
        )
        index = json.loads((directory / "index.json").read_text("utf-8"))
        pending = [
            json.loads(s)
            for s in (directory / "annotations-pending.jsonl")
            .read_text("utf-8").splitlines() if s.strip()
        ]
        if len(pending) != index["clip_count"] or not pending:
            raise AssertionError("The review index and annotations disagree")
        if index["audio_sha256"] != file_digest(audio):
            raise AssertionError("Review pack is not bound to the real source")
        if index["machine_transcript_included"] or index["reference_transcript_included"]:
            raise AssertionError("Review index is mislabeled as including transcript")
        if any(row["reference_text"] or row["reviewer_attestation"] or
               row["review_state"] != "pending" for row in pending):
            raise AssertionError("An unreviewed reference was incorrectly attested")
        if not (directory / "review.html").is_file():
            raise AssertionError("Private offline listening page is missing")

        # Probe every actual FFmpeg-exported WAV by parsing the PCM container,
        # not merely checking that files of nonzero length exist.
        total_sampled_seconds = 0.0
        for clip in index["clips"]:
            file = directory / clip["clip_file"]
            with wave.open(str(file), "rb") as data:
                if data.getnchannels() != 1 or data.getsampwidth() != 2 or \
                   data.getframerate() != 16000 or data.getnframes() <= 0:
                    raise AssertionError("Invalid private PCM WAV audio")
                measured = data.getnframes() / data.getframerate()
            intended = clip["end_seconds"] - clip["start_seconds"]
            if abs(measured - intended) > 0.18:
                raise AssertionError("Review audio is not time-aligned to its interval")
            total_sampled_seconds += measured

        score = evaluate_reviews(result, pending, file_digest(audio))
        if score["scored_rows"] != 0 or score["full_recording_wer"] is not None or \
           score["aggregate"]["micro_wer"] is not None:
            raise AssertionError("Unreviewed source acquired a false accuracy score")
        return {
            "private_pack_generated_on_real_source": True,
            "source_sha256_match": True,
            "private_pcm_wav_probes_passed": len(index["clips"]),
            "sampled_audio_seconds": round(total_sampled_seconds, 2),
            "review_rows": len(pending),
            "unreviewed_rows": len(pending),
            "human_verified_rows": 0,
            "excerpt_wer": None,
            "whole_recording_wer": None,
            "private_pack_uploaded": False,
            "review_requires_actual_human_listening": True,
        }
