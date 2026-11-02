# Nass v0.5 long-form ASR evaluation — 2026-11-02

This report documents completed real, local-media tests. It is **not**
a demonstration of YouTube downloading from the production Render host.

## Real repeated English speech — seam regression

* Fixture: OpenAI Whisper's integrity-checked public-domain `jfk.flac`.
* Processed recording: **88.0 seconds**, concatenated repeated speech.
* Inference: `faster-whisper/tiny.en`, CPU int8, 20-second windows, 4-second overlap.
* Total ASR decoder windows: **6**.
* Recognized segments: **14**.
* Structural anomaly count: **0** on the corrected implementation.
* Timelines: monotonic, speech recognized through the end.
* Real MCP job, transcript paging, structural QA: **passed**.
* This is a technical seam test, NOT an English accuracy study.
* Run: https://github.com/Mosabomer2000/-nass-mcp/actions/runs/41501457666

The first real test exposed backward time ordering and overlap in merged
segments. The corrected code clamps segment timestamp metadata to disjoint
ownership ranges. This does not prove that every word at a boundary is
recovered correctly.

## Real Arabic comparison — 10 concatenated FLEURS clean recordings

* Dataset: Bayanat Labs Arabic ASR Channel Pairs v0.1.0; FLEURS Egyptian
  Arabic clean/test 0..9.
* Audio files: **all ten SHA-256 validated** against published metadata.
* Rights: CC BY 4.0 audio, CC BY-SA 4.0 published reference text.
* **No voice/audio or reference/prediction words** in uploaded CI artifacts.
* Ground truth: 216 published reference words, **not separately audited by
  a human against the speech**. Normalization: `arabic_basic`.
* Concatenated file duration: **125.66 seconds**.
* Recognition: `faster-whisper/small`, CPU int8, beam size 3.
* Both runs: completed real decoding, ASR, job persistence, transcript
  delivery, and structural QA; timestamp order was valid.

| Setting | Decoder windows | Reference words | Micro-WER | Micro-CER |
|---|---:|---:|---:|---:|
| Single pass (`NASS_ASR_CHUNK_SECONDS=0`) | 1 | 216 | 32.407% | 17.840% |
| 20-second chunks, 4-second overlap | 8 | 216 | 36.111% | 19.479% |

**Difference:** 3.704 percentage points higher WER with frequent
20-second window boundaries on this particular artificial sequence.

The earlier **22.685% WER** for `small` on the ten audio clips
**transcribed separately** should not be conflated with the continuous-file
results: the audio segmentation and decoding contexts differ. Comparing
the exact same concatenated audio with/without windowing isolates a
chunk-setting-associated difference, not its full causal mechanism.

* Paired acceptance evidence:
  https://github.com/Mosabomer2000/-nass-mcp/actions/runs/41502455968
* Test harness: `scripts/arabic_longform_acceptance.py`
* Source: https://huggingface.co/datasets/Bayanat-Labs/arabic-asr-channel-pairs

## Production interpretation

The **default long-form window is 480 seconds**, not the 20-second
stress-test setting. No evidence here estimates the accuracy cost of
480-second windows, genuine two-hour lectures, a single continuous human
speaker, or hadith/Quranic technical vocabulary. Human audit of excerpts
on both sides of a seam remains necessary.

For a capable local host, avoid unnecessarily small chunks. When the
recording fits in RAM and duration limits, a single-pass transcription
may produce better wording. For genuinely long recordings, bounded
windows trade decoder context for predictable temporary memory usage.

The repository's JSON `recognition` metadata records model, CPU/GPU
settings, and configured chunk strategy without revealing initial
prompts or private absolute model paths.

**Release gate:** YouTube acquisition still fails on tested GitHub
cloud egress. A successful operator-controlled YouTube `audio`
transcription plus manually checked Arabic passages is still needed
before calling the whole service production ready.
