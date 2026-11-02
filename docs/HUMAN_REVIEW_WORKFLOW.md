# Human-verified listening audit for full-length Arabic recordings

Nass can generate a timestamped transcript from an original spoken recording,
but **a completed job, no detected structural anomalies, and sensible-looking
words do not constitute independently confirmed accuracy**.

This local-only helper prepares exact review intervals around chunk boundaries,
without uploading the original audio, its transcript, or the human annotations.

```bash
# Use the exact source audio from NASS_MEDIA_DIR and the completed job's result.json.
python scripts/manual_audio_review.py template \
  --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
  --audio "$NASS_MEDIA_DIR/lecture.flac" \
  --output "$HOME/private-nass-review.jsonl"

# Listen to every interval, fill reference_text *from the source recording*,
# and mark review_state = human_checked; reviewer_attestation = true.
# Do not mark machine captions as if human-verified.
python scripts/manual_audio_review.py score \
  --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
  --audio "$NASS_MEDIA_DIR/lecture.flac" \
  --manifest "$HOME/private-nass-review.jsonl" \
  --output "$HOME/private-nass-review-scores.json"
```

The program verifies a SHA-256 digest of the exact audio; rejects missing
or inconsistent timestamps, copied references to another recording,
overlapping audit intervals, and model utterances crossing an audit boundary.
Only *self-attested* reviewed excerpts enter the numerator/denominator.

The **resulting WER/CER apply solely to the audited intervals**. This cannot
establish whole-lecture WER and is not proof that a reviewer listened correctly.
All labels are private user-supplied data. The annotations and sampled words
must not be uploaded to public GitHub Actions artifacts.

One can generate the review form independently of access to YouTube; the
recording must be locally accessible and actually processed through audio-ASR.

For less biased inspection, `template --controls 8` also proposes deterministic,
non-overlapping **interior control intervals** away from decoder seams. The
control positions are derived from the audio digest, not from model accuracy.
If the recording is too short or seam intervals dominate, fewer controls may
be available. Compare seam and interior excerpt WER separately; do not infer
full-recording accuracy from either sample alone.

The local report now includes separate `metrics_by_review_kind` aggregates for
`decoder_seam`, `interior_control` and custom excerpts. Only attested,
fully contained, non-overlapping reviewed intervals can contribute to these
statistics. Null values mean no qualifying reviewed reference exists; they
are never treated as 0% word error.


## Private listening pack: WAV clips rather than timestamps alone

After generating the local JSONL template, create a **new private directory**
of numbered WAV excerpts (16-kHz mono PCM) and a word-free index.json:

    python scripts/export_review_clips.py \
      --audio "$NASS_MEDIA_DIR/lecture.flac" \
      --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
      --manifest "$HOME/private-nass-review.jsonl" \
      --output-dir "$HOME/private-nass-clips-001"

The pack includes each seam and interior-control excerpt from the annotation
manifest, using accurate FFmpeg seeking. Every review interval is bound to the
SHA-256 of the exact audio, checked against the ASR job duration and physical
file, and must be disjoint and no longer than 180 seconds. Each clip and the
index are created with restrictive filesystem permissions (0700 directory,
0600 files). An existing output directory is **never overwritten**.

Open index.json to associate clip_0001.wav, etc., with the original review
row IDs. Listen to the WAV clips and enter corrected reference text into the
**original JSONL**, not index.json. Then run the existing scoring command above.

**Important:** Clips are not uploaded or published. They may contain
identifiable voices; keep the folder off public repositories, shared mounts,
and public CI artifacts. The audio remains subject to its original licence.
This export does not attest human review, certify transcription accuracy,
or change the remaining YouTube-acquisition release gate.

Audit-group integrity: the scorer now checks the stored decoder-window plan. A row labelled `decoder_seam` must actually contain a decoder seam, and an `interior_control` row must not contain one. Mislabelled intervals are excluded rather than inflating a seam/control comparison. These automated checks do not establish that a reviewer actually listened.


## Browser-based offline listening and annotation (new)

After \`scripts/export_review_clips.py\` completes, open
\`$HOME/private-nass-clips-001/review.html\` in a browser on the **same machine**.
This is a standalone HTML file; there is no server, CDN, user account, or API
request. It offers each exact-audio WAV clip, its source time range, an Arabic
transcription input field, and an unchecked **human-listening attestation**.
It does NOT embed any original ASR words or prefill a supposed reference.

For each clip:
1. Listen to the WAV (multiple times if necessary).
2. Type precisely the audible words; leave uncertain passages unverified.
3. Check the explicit attestation only for audio you actually reviewed.
4. Press **تصدير ملف المراجعة JSONL** to download \`nass-reviewed.jsonl\`.

The export contains verified rows only when the review checkbox is marked
**and** the reference is nonempty. All other rows remain pending and do not
enter WER/CER. Score using the generated file:

    python scripts/manual_audio_review.py score \
      --result "$NASS_DATA_DIR/jobs/JOB_ID/result.json" \
      --audio "$NASS_MEDIA_DIR/lecture.flac" \
      --manifest "$HOME/Downloads/nass-reviewed.jsonl" \
      --output "$HOME/private-nass-review-scores.json"

The download location varies by browser. Saving the JSONL is an explicit
manual action; browser reloads erase unsaved text. The HTML and its index
contain only identifier/timestamp/digest metadata. **Neither the UI nor its
exports certify that listening actually occurred**; attestation relies on
reviewer honesty. All WAV clips and generated JSONL are confidential unless
the source licence and recorded speakers' rights permit sharing. Do not open
this private review folder from a remotely synchronized or shared drive.


## Resume without losing a long review session

The offline page has an **استئناف المراجعة من ملف JSONL محفوظ** file chooser.
To resume, reopen the original local \`review.html\`, choose the last
\`nass-reviewed.jsonl\` export, and continue correcting the restored entries.
The importer accepts only a manifest whose SHA-256, exact sample IDs,
sample kinds, source intervals, and row count match the loaded review
session. It rejects duplicate IDs, malformed states and unpaired
attestation flags; on error it leaves all current edits untouched.
A file from another recording **cannot** be imported into this session.

No browser cloud storage, network call, automatic saving, or uploading is
used. This is intentionally **explicit checkpointing**: export JSONL
regularly and keep it safe. The page warns before navigation with unsaved
changes; after a download is initiated, confirm the file was really saved.
The import status message indicates whether restoration succeeded.

A separate real-browser acceptance runs in CI using a synthetic tone WAV:
it checks the local sibling WAV player, download JSONL, restoration after a
page reload, and rejection of a deliberately wrong-audio manifest. Neither
the test nor a successful result constitutes human verification of actual
Arabic transcription. Run locally with \`pip install playwright\`, a
Chrome/Chromium binary, and \`python scripts/browser_review_acceptance.py\`.
