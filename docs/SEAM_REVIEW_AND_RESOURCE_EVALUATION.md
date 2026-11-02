# Nass v0.5 — manual seam review, resource telemetry and Arabic reference audit

This release-stage note separates **technical success**, **memory observation**, and
**speech accuracy**. None is interchangeable with another.

## 1. Manual review at long-form decoder boundaries

After a completed `faster-whisper` audio job, call:

```
nass_seam_review(job_id, start_seam=0, count=8, context_seconds=5, include_text=true)
```

For each internal decoder-window seam, the MCP tool returns the position,
the exact audio interval to listen to, the nearby stored segment timestamps,
and optionally the words the model proposed. Page with `next_seam`.

* Use `nass_audio_excerpt` on the returned `listen_from_seconds` interval
  where the original audio is accessible.
* Set `include_text=false` in CI or other redacted diagnostics; then the
  review data contain no transcript wording.
* Text is capped to 180 characters per shown segment, at most eight nearby
  segments and twenty seams per page.
* A window with no segments may be silent: this cannot be classified
  automatically as missing speech. Timestamps do not prove precise alignment.
* **Human review is not yet saved as a verified/corrected text track.**
* Jobs from before the ASR model recorded `recognition.duration_seconds`
  cannot infer seams safely and return a useful unsupported-state message.

Forcing `mode=audio` on a YouTube job is required when exact spoken words
rather than subtitles are the objective.

## 2. CPU and memory observation

`scripts/host_acceptance.py` (and the dedicated English and Arabic
long-form acceptance workflows) now return a `resource_profile` object.
On POSIX it contains:

* The parent process's **lifetime peak RSS** in MB.
* The highest peak RSS of **individual terminated children** (FFmpeg), not
  the simultaneous sum of all child processes.
* CPU user/system seconds consumed between the beginning and end of the test.

Memory is a **lifetime high-water mark**, not a per-job delta or a
guaranteed requirement on another machine. GPU VRAM is not measured.
The test process's memory baseline, model cache, dependencies, and
GitHub Actions runner architecture can influence these figures.

Initial verified measurements on a GitHub-hosted CPU runner:

| Audio case | ASR model | Duration | Windows | Parent process lifetime peak RSS |
|---|---|---:|---:|---:|
| Repeated public-domain English speech | tiny.en | 88 seconds | 6 | 444.80 MB |
| Ten concatenated FLEURS Arabic clips, one pass | small | 125.66 seconds | 1 | 1153.35 MB |
| Same concatenated Arabic audio, 20-second chunks | small | 125.66 seconds | 8 | 912.96 MB |

These are **separate processes and point observations**, not a controlled
memory benchmark or verified requirements for a 2-hour lecture.

Evidence:
- https://github.com/Mosabomer2000/-nass-mcp/actions/runs/41507226837
- https://github.com/Mosabomer2000/-nass-mcp/actions/runs/41507226825

## 3. More trustworthy short Arabic references: NahwAI

The dataset card for `NahwAI/arabic-tashkeel-speech` says its 1,093
recordings by ten speakers were *reviewed and approved by human annotators*.
It is licensed CC BY 4.0. Unlike the earlier FLEURS-derived test in which
Nass used published prompts with no reported direct audio verification,
this provides publisher-reviewed sentence-level speech references.

Dataset: https://huggingface.co/datasets/NahwAI/arabic-tashkeel-speech

An initial ten-clip run with `faster-whisper/small`, CPU int8, beam 3,
`arabic_basic` normalization, completed all samples. It compared 42
reference words: **26.19% WER and 7.98% CER**. This is only a tiny
diagnostic sample, **not** evidence of general model accuracy.

Evidence: https://github.com/Mosabomer2000/-nass-mcp/actions/runs/41507510389

A broader 40-clip, deterministic distributed-index evaluation has its
own workflow `.github/workflows/nahw-asr.yml`. Source audio is
downloaded only for testing; neither source bytes nor reference text is
uploaded to public artifacts. Report its actual result from CI, not a
predicted value. Publisher review does not equal independent Nass
re-auditing of every utterance.

## 4. Remaining limitations and production gate

* A natural **continuous 30–120-minute Arabic lecture** with explicit,
  compatible recording rights and manually audited excerpts has NOT been
  benchmarked yet. Repeated or concatenated short clips do not simulate
  discourse continuity.
* A third-party long-form data mirror may inherit video rights or
  machine-generated captions. Validate both before using it as reference
  truth; the dataset's licence label alone is not a substitute.
* Audio acquisition from YouTube remains blocked by bot checks on the
  tested cloud runners. This entire suite does not solve that blocker.
* PR #2 stays open; the existing Render deployment is unchanged.
