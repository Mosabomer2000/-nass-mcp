# Nass operator-controlled host acceptance (no privileged credentials)

YouTube's bot-check on GitHub-hosted and Render egress cannot be fixed by
passing another offline unit test. This script tests **the machine that actually
runs the MCP**, without exfiltrating its transcript or access credentials.

## Step 1: Real local audio, no YouTube involved

Install Python 3.11/3.12 and FFmpeg and run from the repository checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[all,remote]'
mkdir -p "$HOME/nass-input" "$HOME/nass-data"
export NASS_MEDIA_DIR="$HOME/nass-input"
export NASS_DATA_DIR="$HOME/nass-data"
export NASS_WHISPER_MODEL=small
export NASS_DEVICE=cpu
export NASS_COMPUTE_TYPE=int8
export NASS_ALLOW_EXTERNAL_ASR=0
# Copy a recording you own or are permitted to process to $NASS_MEDIA_DIR
python scripts/host_acceptance.py --local-file mylecture.wav --language ar
```

The report `nass-host-acceptance.json` records whether real audio decoding,
local Whisper inference, MCP job handling, transcript paging, and structural
quality checks succeeded. **It does not publish or score your private words.**

## Step 2: Test a public YouTube video on this *same* operator machine

```bash
python scripts/host_acceptance.py \
  --youtube 'https://youtu.be/VIDEO_ID' --language ar \
  --max-wait 1800 --output nass-youtube-host-check.json
```

This MUST use `mode=audio`, not available captions. A success requires
actual YouTube audio acquisition and local ASR, not merely returning
auto-generated subtitles. If blocked, the report includes sanitized failure
categories, **never raw error messages**.

Only configure BgUtils PO-token support after inspecting its installation
guide. Provider presence alone does not establish token generation, successful
login, or YouTube access. Never share your browser cookies or the unauthenticated
provider port publicly. Run any HTTP gateway behind authenticated HTTPS.

Test results from a hosted CI runner are **not transferable** to your home
network, and vice versa; the relevant variable may be host/IP or provider
configuration.

For a valid release gate, human-review an Arabic sample against the exact
source audio and record word-level mismatches. Neither this script nor the
structural QA tool claims to establish transcript correctness.
