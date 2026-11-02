# Arabic ASR benchmark harness (local, reproducible, opt-in)

`scripts/arabic_asr_benchmark.py` measures real locally transcribed audio
against aligned references. No YouTube downloads or paid APIs are required.

The manifest is UTF-8 JSONL. Each line has:
`id`, `audio` (relative to `NASS_MEDIA_DIR`), `reference`, `reference_quality`
(`human_verified` or `unverified`), `source`, `license`, and optional
`language` (`ar` or `en`).

Do not label machine-generated captions as human-verified references.
The evaluator reports aggregate micro-WER and micro-CER, and *separate*
human-verified scores. Normalization uses an explicitly documented policy.
Both versions preserve the original transcript; aggressive normalization
is applied only to comparisons. WER can legitimately exceed 100%.

Example:

```bash
export NASS_MEDIA_DIR="$PWD/media"
export NASS_DATA_DIR="$PWD/.nass-eval"
export NASS_WHISPER_MODEL=small
export NASS_DEVICE=cpu
export NASS_COMPUTE_TYPE=int8
python scripts/arabic_asr_benchmark.py --manifest evaluation/arabic.jsonl \
    --policy arabic_basic --output evaluation/results/whisper-small.json
```

For a rights-cleared starting point, see the Google FLEURS Egyptian Arabic
test split or Bayanat Labs' Arabic ASR Channel Pairs (CC BY 4.0 audio,
CC BY-SA 4.0 reference text). Preserve the dataset attribution and split.
Never redistribute any recording in the Nass repo without checking its
individual licence and speaker privacy conditions.

References:
- https://huggingface.co/datasets/Bayanat-Labs/arabic-asr-channel-pairs
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/openai/whisper
