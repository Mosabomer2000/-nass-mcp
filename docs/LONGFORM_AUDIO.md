# Long-form local audio ASR (Nass v0.5 branch)

The actual `faster-whisper` backend automatically uses bounded, overlapping
decoder windows for recordings exceeding the configured chunk length.

* Default chunk length: **480 seconds** (8 minutes).
* Default overlap: **4 seconds**.
* A single local model is loaded into the worker process. At most one temporary
  16 kHz mono PCM WAV chunk is retained during recognition, then deleted.
* Every word/segment belongs to the window containing its estimated midpoint.
  An overlap seam is assigned once; no successive-window duplicate is simply
  concatenated.
* The original short-audio pathway is retained for recordings up to the
  configured chunk length.
* If any chunk extraction or inference raises an error, the whole backend
  attempt is marked failed; a partial transcript is **not** silently accepted.
* `NASS_ASR_CHUNK_SECONDS=0` explicitly disables segmentation and retains the
  previous one-pass behavior.
* Windows can contain silence: zero recognition segments in one chunk is
  permitted. An entirely empty transcript is still rejected by the ASR
  provider dispatch.

## Configuration

```bash
export NASS_ASR_CHUNK_SECONDS=480
export NASS_ASR_OVERLAP_SECONDS=4
export NASS_WHISPER_MODEL=small
export NASS_DEVICE=cpu
export NASS_COMPUTE_TYPE=int8
```

**Scientific qualification:** VAD and Whisper segments estimate utterance
boundaries; the midpoint merge does not prove exact phonetic timestamps or
absence of missing syllables at seams. Real Arabic lecture acceptance should
inspect segments immediately before and after each window boundary, especially
for Quranic verses, hadith chains, and technical terms. Overlapping windows do
not introduce model confidence or source verification. The job is not
checkpoint-resumable across server restarts.

`NASS_ASR_CHUNK_SECONDS` must be 0 or 4..1800; overlap must be in 0..30
and less than half the chunk width. Real audio is tested with FFmpeg in
`tests/test_longform.py`; complete model behavior requires a separately
triggered live-speech acceptance test.
