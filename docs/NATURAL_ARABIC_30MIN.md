# Natural 30-minute Arabic conversation acceptance — controlled source

This is a **natural, unspliced recording**, not the earlier synthetic join of
short FLEURS read-speech clips.

## Source and rights

- Wikimedia Commons file: [ARABIC SPEAKING COMMUNITY Conversation hour.webm](https://commons.wikimedia.org/wiki/File:ARABIC_SPEAKING_COMMUNITY_Conversation_hour.webm)
- Self-published work attributed on Commons to **Sandra Hanbo**, dated
  **2023-01-26**. Wikimedia Commons identifies **CC BY-SA 4.0**.
- The source recording lasts approximately 79 minutes 56 seconds; the
  controlled CI test takes the first 30 minutes only.
- Exact original file byte count: **86,747,334**.
- Commons source SHA-1: `868f164bcbedc117cc358b344fa305a00b741141`.
- Both expected length and original checksum are verified before extraction.
- Original audio/media and machine-recognized words are NOT included in
  repository commits or GitHub Actions artifacts.

Original description/licensing:
https://commons.wikimedia.org/wiki/File:ARABIC_SPEAKING_COMMUNITY_Conversation_hour.webm

## Technical acceptance

The source is converted on a transient worker to 16 kHz mono FLAC,
retaining its first 1800 seconds of audio. Three speech-language checks
are sampled from widely separated time offsets so the file title alone
does not establish that the speech is predominantly Arabic.

Only when at least two samples are identified as Arabic does the worker
run the actual `nass_start_local_file` MCP tool. It demands actual
`asr:faster-whisper` output and then checks job completion, transcript
delivery, structural QA, chronology, speech through much of the recording,
and paginated seam-review availability.

This gate uses `faster-whisper/small`, CPU/int8, and the default
**480-second windows / four-second overlap**. Both peak memory and elapsed
CPU time are recorded, with the limitations of process accounting made clear.

No source-aligned, human-audited reference is available for this original
recording, so **WER and CER must remain null**. A successful run establishes
engineering feasibility for this particular natural Arabic audio, **not**
the correctness of every utterance. A human will still have to listen
to the seam excerpts and other selected passages.

Workflow:
https://github.com/Mosabomer2000/-nass-mcp/actions/workflows/natural-arabic-30min.yml

## Manual verification of this and other full-length recordings

Local-only command:

```bash
python scripts/manual_audio_review.py template \
  --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
  --audio "$NASS_MEDIA_DIR/lecture.flac" \
  --output "$HOME/private-review.jsonl"
```

Fill the references from **the actual audible words**, mark each reviewed
section `review_state=human_checked` and `reviewer_attestation=true`, then:

```bash
python scripts/manual_audio_review.py score \
  --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
  --audio "$NASS_MEDIA_DIR/lecture.flac" \
  --manifest "$HOME/private-review.jsonl" \
  --output "$HOME/private-audit-metrics.json"
```

The score is always explicitly excerpt-based, never full-audio WER.
Do not upload private annotation manifests publicly.

The 30-minute Wikimedia test bypasses YouTube to evaluate ASR; it
**does not resolve the YouTube source-access obstacle** on GitHub
or the production Render instance.

## Verified real run — 2026-11-02

GitHub Actions:
https://github.com/Mosabomer2000/-nass-mcp/actions/runs/41512718220

**SUCCESS** on the first 30 minutes of the complete, checksum-verified natural
Commons recording. The test did not use YouTube, paid API, or a mock ASR engine.

| Measurement | Observed |
|---|---:|
| Audio duration | 1800.0 s |
| Whisper model | small, CPU/int8, beam 3 |
| Chunk size/overlap | 480 s / 4 s |
| Decoder windows | 4 |
| Output speech segments | 560 |
| Original transcript characters | 25,735 |
| Original audio-to-MCP acceptance elapsed | 478.26 s |
| Structural timestamp anomalies | 0 |
| Distinct decoder-window seams for human review | 3 |
| Parent process peak RSS since process start | 1806.98 MB |
| Word-error rate / character-error rate | **not measured** |

**Language detection matters:** the source is *not fully Arabic*.
Three separate samples (offsets 90, 660 and 1250 seconds) were classified
respectively **Arabic (0.8114)**, **Arabic (0.8940)** and
**English (0.9165)** by the model's audio-language detector.
This proves a successful **natural bilingual Arabic/English discussion**
under an Arabic language hint; it does not prove 30 minutes of purely
Arabic speech or that English code-switching was transcribed accurately.

The RSS value is a lifetime high-water mark from this particular Linux
worker, not a hard requirement or a per-job incremental footprint.
The recording and ASR text were not published as CI artifacts.
A complete human-aligned reference transcript was not available, so
WER/CER remain null rather than fabricated. The three seams still require
listening and correction where appropriate.

The run validates audio transcription, real MCP job completion,
paginated delivery, chronological timestamps, structural QA,
and seam-review access in a continuous natural recording; it does **not**
validate YouTube source acquisition.
