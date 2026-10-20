# Nass MCP full audio backend: Node 22 (yt-dlp EJS), Python 3.11, FFmpeg.
# This is an experimental low-memory deployment, NOT tested against live YouTube.
FROM node:22-bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    NASS_HOST=0.0.0.0 \
    NASS_DATA_DIR=/tmp/nass-data \
    HF_HOME=/tmp/nass-model-cache \
    NASS_WHISPER_MODEL=tiny \
    NASS_DEVICE=cpu \
    NASS_COMPUTE_TYPE=int8 \
    NASS_BEAM_SIZE=1 \
    NASS_WORKERS=1 \
    NASS_JOB_QUEUE_LIMIT=1 \
    NASS_AUDIO_CACHE_LIMIT_BYTES=104857600 \
    NASS_MAX_DURATION_SEC=1200 \
    NASS_MAX_AUDIO_BYTES=62914560
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --disable-pip-version-check \
        '.[captions,audio,asr,remote]' \
    && NODE_DIR="$(python -c 'from pathlib import Path; import nass_mcp; print(Path(nass_mcp.__file__).resolve().parent / "_node")')" \
    && test -f "$NODE_DIR/youtubejs_audio.mjs" \
    && npm install --prefix "$NODE_DIR" --omit=dev --no-audit --no-fund \
    && test -d "$NODE_DIR/node_modules/youtubei.js" \
    && node --version && python -c 'from importlib.util import find_spec; assert find_spec("mcp")'
# Pre-created scratch area. Free Render disk and weights are ephemeral.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin nass \
    && mkdir -p /tmp/nass-data /tmp/nass-model-cache \
    && chown -R nass:nass /tmp/nass-data /tmp/nass-model-cache /app
USER nass
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn nass_mcp.remote:app --host 0.0.0.0 --port ${PORT:-10000} --no-proxy-headers"]
