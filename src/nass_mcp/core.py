"""Transcription engine independent of MCP's transport and network.

External providers are imported lazily; a failure in one backend never disables the
rest. No proxies, cookies, authentication bypasses or captcha-solving are included.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import time
import subprocess
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timezone
from typing import Callable, Any
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

ROOT = Path(os.environ.get("NASS_DATA_DIR", Path.home() / ".cache" / "nass-mcp")).expanduser().resolve()
MEDIA_ROOT = Path(os.environ.get("NASS_MEDIA_DIR", ROOT / "input")).expanduser().resolve()
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                 "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus", ".webm", ".mp4"}
MAX_AUDIO_BYTES = int(os.environ.get("NASS_MAX_AUDIO_BYTES", str(350 * 1024 * 1024)))
MAX_DURATION_SEC = int(os.environ.get("NASS_MAX_DURATION_SEC", str(4 * 3600)))
MAX_OUTPUT_CHARS = 20000
CAPTION_CACHE_SECONDS = int(os.environ.get("NASS_CAPTION_CACHE_SECONDS", "86400"))
AUDIO_CACHE_LIMIT_BYTES = int(os.environ.get("NASS_AUDIO_CACHE_LIMIT_BYTES", str(3 * 1024**3)))
JOB_QUEUE_LIMIT = max(1, int(os.environ.get("NASS_JOB_QUEUE_LIMIT", "8")))
PROVIDER_TIMEOUT = max(30, int(os.environ.get("NASS_PROVIDER_TIMEOUT", "600")))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_video_id(url: str) -> str:
    """Allow only canonical YouTube hosts or a single 11-character YouTube ID."""
    url = url.strip()
    if VIDEO_ID.fullmatch(url):
        return url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.hostname not in ALLOWED_HOSTS:
        raise ValueError("Only public youtube.com/youtu.be links or a video ID are allowed")
    if p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError("Unsupported URL authority")
    if p.hostname in ("youtu.be", "www.youtu.be"):
        value = p.path.strip("/").split("/")[0]
    elif p.path in ("/watch", "/"):
        value = parse_qs(p.query).get("v", [""])[0]
    elif p.path.startswith(("/shorts/", "/live/", "/embed/", "/v/")):
        value = p.path.split("/")[2]
    else:
        value = ""
    if not VIDEO_ID.fullmatch(value):
        raise ValueError("Invalid or unsupported YouTube video identifier")
    return value


def canonical_url(video_id: str) -> str:
    return "https://www.youtube.com/watch?v=" + get_video_id(video_id)


def safe_input_audio(filename: str) -> Path:
    """Restrict local media access to the dedicated intake directory."""
    candidate = (MEDIA_ROOT / filename).resolve()
    if candidate != MEDIA_ROOT and not candidate.is_relative_to(MEDIA_ROOT):
        raise ValueError("Audio path must be inside the configured media directory")
    if not candidate.is_file() or candidate.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError("Audio file missing or its extension is not allowed")
    if candidate.stat().st_size > MAX_AUDIO_BYTES:
        raise ValueError("Audio input exceeds configured size limit")
    return candidate


def safe_error(exc: Exception) -> str:
    # Do not leak command-line paths/credentials in user-visible MCP tool results.
    if isinstance(exc, subprocess.TimeoutExpired):
        return "TimeoutExpired: provider exceeded its time limit"
    if isinstance(exc, subprocess.CalledProcessError):
        return f"CalledProcessError: provider exited with code {exc.returncode}"
    s = str(exc).splitlines()[0][:240]
    for private_path in (str(ROOT), str(MEDIA_ROOT), str(Path.home())):
        if private_path and private_path != "/":
            s = s.replace(private_path, "[server-path]")
    for secret in (os.environ.get("GROQ_API_KEY", ""), os.environ.get("NASS_BEARER_TOKEN", "")):
        if secret:
            s = s.replace(secret, "[redacted]")
    return f"{type(exc).__name__}: {s}"


def to_segments(items: list[dict], offset: float = 0) -> list[dict]:
    out = []
    for item in items:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = max(0.0, float(item.get("start", 0)) + offset)
        end = item.get("end")
        if end is None:
            end = float(item.get("start", 0)) + float(item.get("duration", 0))
        end = max(start, float(end) + offset)
        out.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return out


def seconds_to_srt(sec: float) -> str:
    ms = max(0, int(round(sec * 1000)))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def srt_text(segments: list[dict]) -> str:
    return "\n\n".join(f"{i}\n{seconds_to_srt(s['start'])} --> {seconds_to_srt(s['end'])}\n{s['text']}"
                       for i, s in enumerate(segments, 1)) + "\n"


def parse_srt(content: str, offset: float = 0.0) -> list[dict]:
    out = []
    # tolerate either periods or commas in SRT timecodes
    pattern = re.compile(r"(?m)^(?:\d+\s*\n)?(\d\d:\d\d:\d\d[,.]\d+)\s*-->\s*(\d\d:\d\d:\d\d[,.]\d+).*?\n(.*?)(?=\n\s*\n|\Z)", re.S)
    def decode(t):
        hours, minutes, rest = t.replace(",", ".").split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)
    for start, end, text in pattern.findall(content.strip()):
        clean = " ".join(x.strip() for x in text.splitlines() if x.strip())
        if clean:
            out.append({"start": decode(start) + offset, "end": decode(end) + offset, "text": clean})
    return out


def parse_vtt(content: str) -> list[dict]:
    # VTT captions often duplicate rolling text; coalesce only adjacent exact duplicates.
    blocks = re.split(r"\n\s*\n", content.replace("\r", ""))
    out = []
    for block in blocks:
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"(?:(\d\d):)?(\d\d):(\d\d)[.,](\d+)\s*-->\s*(?:(\d\d):)?(\d\d):(\d\d)[.,](\d+)", line)
            if not m:
                continue
            def stamp(h, minute, sec, frac):
                return (int(h or 0)*3600 + int(minute)*60 + int(sec) + float("0."+frac))
            text = " ".join(re.sub(r"<[^>]+>", "", s).strip() for s in lines[i+1:] if s.strip())
            if text:
                start = stamp(*m.groups()[:4])
                end = stamp(*m.groups()[4:])
                if not out or text != out[-1]["text"]:
                    out.append({"start": start, "end": end, "text": text})
                else:
                    out[-1]["end"] = end
            break
    return out


def parse_json3(content: str) -> list[dict]:
    data = json.loads(content)
    parts = []
    for event in data.get("events", []):
        phrase = "".join(seg.get("utf8", "") for seg in event.get("segs", []))
        if phrase.strip():
            start = event.get("tStartMs", 0) / 1000
            end = start + event.get("dDurationMs", 0) / 1000
            parts.append({"start": start, "end": end, "text": phrase.strip()})
    return parts


@dataclass
class Attempt:
    stage: str
    provider: str
    ok: bool
    message: str = ""


@dataclass
class Result:
    video_id: str
    source: str
    segments: list[dict] = field(default_factory=list)
    language: str = "auto"
    audio_source: str = ""
    attempts: list[dict] = field(default_factory=list)
    verification: dict | None = None
    def to_dict(self) -> dict:
        return {"video_id": self.video_id, "source": self.source, "language": self.language,
                "audio_source": self.audio_source, "segments": self.segments,
                "text": "\n".join(s["text"] for s in self.segments),
                "attempts": self.attempts, "verification": self.verification,
                "is_audio_asr": self.source.startswith("asr:")}


@lru_cache(maxsize=2)
def load_whisper_model(model_name: str, device: str, compute_type: str):
    # Lazy + process-local cache: avoid loading large ASR weights for each job.
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device=device, compute_type=compute_type)


class Engine:
    """Adaptive provider cascade. Providers are separate failure domains where feasible."""
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def yt_captions(self, video_id: str, language: str) -> tuple[list[dict], str]:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        listed = list(api.list(video_id))
        requested = [t for t in listed if language in ("", "auto") or
                     t.language_code.lower() == language.lower() or
                     t.language_code.lower().startswith(language.lower()+"-")]
        if not requested:
            raise RuntimeError(f"No YouTube captions in requested language {language}")
        requested.sort(key=lambda t: (t.is_generated, t.language_code != language))
        chosen = requested[0]
        raw = chosen.fetch()
        parts = to_segments([{"start": s.start, "duration": s.duration, "text": s.text} for s in raw])
        if not parts:
            raise RuntimeError("Empty caption track")
        return parts, f"youtube-transcript-api:{chosen.language_code}:{'auto' if chosen.is_generated else 'manual'}"

    def ytdlp_captions(self, video_id: str, language: str, target: Path) -> tuple[list[dict], str]:
        from yt_dlp import YoutubeDL
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("caption.*"):
            if old.is_file() and old.suffix.lower() in (".json3", ".vtt"):
                old.unlink(missing_ok=True)
        options = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
                   "subtitleslangs": ["all" if language in ("", "auto") else language+".*"],
                   "subtitlesformat": "json3/vtt", "outtmpl": str(target / "caption.%(ext)s"),
                   "ignoreerrors": False, "quiet": True, "no_warnings": True, "noplaylist": True,
                   "socket_timeout": 25, "retries": 2, "writeinfojson": False}
        # EJS / YouTube extraction requires explicitly enabling Node 22+ when
        # Deno is absent. Keep a pure-Python fallback if JS is unavailable.
        if shutil.which("node"):
            options["js_runtimes"] = {"node": {}}
        with YoutubeDL(options) as ydl:
            ydl.download([canonical_url(video_id)])
        found = sorted((p for p in target.glob("caption.*") if p.suffix.lower() in (".json3", ".vtt")),
                       key=lambda p: (p.suffix.lower() != ".json3", p.name))
        for p in found:
            data = p.read_text("utf-8")
            parts = parse_json3(data) if p.suffix.lower() == ".json3" else parse_vtt(data)
            if parts:
                return parts, f"yt-dlp-captions:{p.name}"
        raise RuntimeError("yt-dlp returned no parseable subtitle track")

    def ytdlp_audio(self, video_id: str, target: Path, client: str) -> Path:
        from yt_dlp import YoutubeDL
        target.mkdir(parents=True, exist_ok=True)
        options = {"format": "bestaudio[ext=m4a]/bestaudio/best", "noplaylist": True,
                   "outtmpl": str(target / "audio.%(ext)s"), "quiet": True, "no_warnings": True,
                   "ignoreerrors": False, "socket_timeout": 25, "retries": 2,
                   "fragment_retries": 2, "continuedl": True,
                   "max_filesize": MAX_AUDIO_BYTES}
        if shutil.which("node"):
            options["js_runtimes"] = {"node": {}}
        if client != "default":
            options["extractor_args"] = {"youtube": {"player_client": [client]}}
        with YoutubeDL(options) as ydl:
            ydl.download([canonical_url(video_id)])
        files = sorted(p for p in target.glob("audio.*") if p.is_file() and
                       p.suffix.lower() in AUDIO_EXTENSIONS and p.stat().st_size > 4096)
        if not files:
            raise RuntimeError(f"No audio file downloaded with yt-dlp client {client}")
        return files[0]

    def pytubefix_audio(self, video_id: str, target: Path) -> Path:
        from pytubefix import YouTube
        target.mkdir(parents=True, exist_ok=True)
        yt = YouTube(canonical_url(video_id))
        stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
        if stream is None:
            raise RuntimeError("pytubefix found no audio streams")
        if getattr(stream, "filesize", None) and stream.filesize > MAX_AUDIO_BYTES:
            raise RuntimeError("pytubefix audio exceeds limit")
        name = stream.download(output_path=str(target), filename="audio" + "." + stream.subtype)
        result = Path(name)
        if not result.is_file() or result.stat().st_size > MAX_AUDIO_BYTES:
            raise RuntimeError("Missing or oversized pytubefix output")
        return result

    def youtubejs_audio(self, video_id: str, target: Path) -> Path:
        """An independent JS/InnerTube audio stream; never loads third-party code dynamically."""
        node = shutil.which("node")
        script = Path(__file__).resolve().parent / "_node" / "youtubejs_audio.mjs"
        # Installed wheel layout may omit scripts; operator can set a trusted fixed script path.
        script = Path(os.environ.get("NASS_YOUTUBEJS_SCRIPT", str(script))).expanduser().resolve()
        if not node or not script.is_file():
            raise RuntimeError("Node or optional YouTube.js adapter not installed")
        target.mkdir(parents=True, exist_ok=True)
        out = target / "audio.m4a"
        out.unlink(missing_ok=True)
        try:
            subprocess.run([node, str(script), get_video_id(video_id), str(out), str(MAX_AUDIO_BYTES)],
                           check=True, capture_output=True, timeout=PROVIDER_TIMEOUT)
        except subprocess.CalledProcessError as exc:
            # Do not echo stderr: it can contain signed media URLs or other secrets.
            # Categorize only known failure messages for safe, actionable reports.
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            if "ERR_MODULE_NOT_FOUND" in stderr or "Cannot find package" in stderr:
                reason = "YouTube.js dependency missing inside installed Python package"
            elif "403" in stderr or "Forbidden" in stderr:
                reason = "YouTube.js request was refused (HTTP 403)"
            elif "bot" in stderr.lower() or "sign in" in stderr.lower():
                reason = "YouTube refused unauthenticated extraction"
            elif "Audio stream exceeds size limit" in stderr:
                reason = "YouTube.js audio exceeds configured maximum"
            else:
                reason = f"YouTube.js subprocess failed with code {exc.returncode}"
            raise RuntimeError(reason) from exc
        return out

    def youtubedr_audio(self, video_id: str, target: Path) -> Path:
        """Independent Go extractor: select AAC audio-only itag 140; fail cleanly if absent."""
        binary = shutil.which("youtubedr")
        if not binary:
            raise RuntimeError("Optional youtubedr command is not installed")
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run([binary, "download", "-q", "140", "-d", str(target),
                        "-o", "audio.m4a", canonical_url(video_id)],
                       check=True, capture_output=True, timeout=PROVIDER_TIMEOUT)
        out = target / "audio.m4a"
        if not out.is_file():
            raise RuntimeError("youtubedr produced no audio-only file")
        return out

    def go_captions(self, video_id: str, language: str, target: Path) -> tuple[list[dict], str]:
        """Use niche Go InnerTube ANDROID/IOS transcript CLI as a third caption implementation."""
        binary = shutil.which("yt-transcript")
        if not binary:
            raise RuntimeError("Optional yt-transcript Go command is not installed")
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.srt"):
            if f"__{video_id}." in old.name:
                old.unlink(missing_ok=True)
        args = [binary, "-srt", "-out", str(target)]
        if language not in ("", "auto"):
            args += ["-lang", language]
        args.append(canonical_url(video_id))
        subprocess.run(args, check=True, capture_output=True, timeout=180)
        # Filename includes trusted eleven-char video_id; do not accept unrelated stale files.
        for path in sorted(target.glob("*.srt")):
            if f"__{video_id}." not in path.name:
                continue
            segments = parse_srt(path.read_text("utf-8"))
            if segments:
                return segments, "yt-transcript-go:innertube"
        raise RuntimeError("yt-transcript produced no readable SRT")

    def acquire_audio(self, video_id: str, work: Path, attempts: list[dict]) -> tuple[Path, str]:
        video_id = get_video_id(video_id)
        if os.environ.get("NASS_AUDIO_CACHE", "1") == "1":
            for cached in sorted((self.root / "audio-cache" / video_id).glob("audio.*")):
                if cached.suffix.lower() in AUDIO_EXTENSIONS and cached.is_file():
                    try:
                        self.check_audio(cached)
                        attempts.append(vars(Attempt("audio", "local-audio-cache", True)))
                        return cached, "local-audio-cache"
                    except Exception:
                        cached.unlink(missing_ok=True)
        methods: list[tuple[str, Callable[[], Path]]] = [
            ("yt-dlp/default", lambda: self.ytdlp_audio(video_id, work / "ytdlp_default", "default")),
            ("yt-dlp/ios", lambda: self.ytdlp_audio(video_id, work / "ytdlp_ios", "ios")),
            # Official yt-dlp guidance: some embeddable videos support this client
            # without a GVS PO token; this cannot fix a blocked datacenter IP.
            ("yt-dlp/web_embedded", lambda: self.ytdlp_audio(video_id, work / "ytdlp_embedded", "web_embedded")),
            ("pytubefix", lambda: self.pytubefix_audio(video_id, work / "pytubefix")),
            ("youtubejs", lambda: self.youtubejs_audio(video_id, work / "youtubejs")),
            ("youtubedr", lambda: self.youtubedr_audio(video_id, work / "youtubedr")),
        ]
        for name, fn in methods:
            try:
                audio = fn()
                self.check_audio(audio)
                if os.environ.get("NASS_AUDIO_CACHE", "1") == "1":
                    try:
                        self._cache_audio(video_id, audio)
                    except (OSError, ValueError):
                        pass  # Disk cache failure never loses a valid audio fetch.
                attempts.append(vars(Attempt("audio", name, True)))
                return audio, name
            except Exception as exc:
                attempts.append(vars(Attempt("audio", name, False, safe_error(exc))))
        raise RuntimeError("All real-audio extraction methods failed; see attempts")

    def _cache_audio(self, video_id: str, audio: Path) -> None:
        # Store only real audio that has already passed media validation.
        base = self.root / "audio-cache" / video_id
        base.mkdir(parents=True, exist_ok=True)
        target = base / ("audio" + audio.suffix.lower())
        temporary = base / ("staging-" + uuid4().hex + audio.suffix.lower())
        try:
            shutil.copy2(audio, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        self._prune_audio_cache()

    def _prune_audio_cache(self) -> None:
        base = self.root / "audio-cache"
        files = sorted((p for p in base.glob("*/audio.*") if p.is_file()),
                       key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for p in files:
            if total <= AUDIO_CACHE_LIMIT_BYTES:
                break
            size = p.stat().st_size
            p.unlink(missing_ok=True)
            total -= size

    def check_audio(self, audio: Path) -> float:
        if audio.stat().st_size > MAX_AUDIO_BYTES:
            raise ValueError("Audio file too large")
        if not shutil.which("ffprobe"):
            raise RuntimeError("ffprobe is required for media validation")
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration:stream=codec_type", "-of", "json", str(audio)],
                           text=True, capture_output=True, timeout=35, check=True)
        data = json.loads(r.stdout)
        if not any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])):
            raise ValueError("Input has no actual audio stream")
        duration = float(data.get("format", {}).get("duration", 0))
        if not 0 < duration <= MAX_DURATION_SEC:
            raise ValueError("Unrecognized duration or video exceeds duration limit")
        return duration

    def faster_whisper_asr(self, audio: Path, language: str) -> list[dict]:
        model_name = os.environ.get("NASS_WHISPER_MODEL", "small")
        model = load_whisper_model(model_name, os.environ.get("NASS_DEVICE", "cpu"),
                                   os.environ.get("NASS_COMPUTE_TYPE", "int8"))
        segments, _ = model.transcribe(str(audio), language=None if language in ("auto", "") else language,
                                       beam_size=max(1, min(5, int(os.environ.get("NASS_BEAM_SIZE", "5")))), vad_filter=True,
                                       initial_prompt=os.environ.get("NASS_INITIAL_PROMPT") or None)
        return to_segments([{"start": s.start, "end": s.end, "text": s.text} for s in segments])

    def whisper_cpp_asr(self, audio: Path, language: str, work: Path) -> list[dict]:
        binary = os.environ.get("NASS_WHISPER_CPP_BIN", "whisper-cli")
        model = os.environ.get("NASS_WHISPER_CPP_MODEL", "")
        if not shutil.which(binary) or not model or not Path(model).is_file():
            raise RuntimeError("whisper.cpp binary/model not configured")
        work.mkdir(parents=True, exist_ok=True)
        wav = work / "mono16.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(audio),
                        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                       timeout=3600, check=True, capture_output=True)
        prefix = work / "whispercpp"
        command = [binary, "-m", model, "-f", str(wav), "-l", language or "auto",
                   "-osrt", "-of", str(prefix)]
        if os.environ.get("NASS_INITIAL_PROMPT"):
            command.extend(["--prompt", os.environ["NASS_INITIAL_PROMPT"]])
        subprocess.run(command, timeout=10800, check=True, capture_output=True)
        output = Path(str(prefix)+".srt")
        if not output.exists():
            raise RuntimeError("whisper.cpp returned no SRT")
        return parse_srt(output.read_text("utf-8"))

    def groq_asr(self, audio: Path, language: str, work: Path) -> list[dict]:
        if os.environ.get("NASS_ALLOW_EXTERNAL_ASR") != "1":
            raise RuntimeError("External ASR not enabled (privacy opt-in)")
        token = os.environ.get("GROQ_API_KEY")
        if not token:
            raise RuntimeError("GROQ_API_KEY not set")
        import requests
        work.mkdir(parents=True, exist_ok=True)
        duration = self.check_audio(audio)
        out = []
        # Send a bounded, low-bitrate compressed 8-minute piece per request.
        # Retry/fallback is handled by outer dispatch; no automatic paid requests.
        for start in range(0, int(duration)+1, 480):
            length = min(480.0, duration-start)
            if length <= 0.05:
                break
            part = work / f"part-{start}.mp3"
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", str(start),
                            "-i", str(audio), "-t", str(length), "-vn", "-ac", "1",
                            "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(part)],
                           check=True, timeout=600, capture_output=True)
            with part.open("rb") as stream:
                data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json"}
                if os.environ.get("NASS_INITIAL_PROMPT"):
                    data["prompt"] = os.environ["NASS_INITIAL_PROMPT"][:350]
                if language not in ("", "auto"):
                    data["language"] = language
                r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                  headers={"Authorization": "Bearer " + token},
                                  files={"file": (part.name, stream, "audio/mpeg")},
                                  data=data, timeout=300)
            r.raise_for_status()
            body = r.json()
            if body.get("segments"):
                segs = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in body["segments"]]
            else:
                segs = [{"start": 0, "end": length, "text": body.get("text", "")}]
            out.extend(to_segments(segs, offset=float(start)))
            part.unlink(missing_ok=True)
        return out

    def speech_to_text(self, audio: Path, language: str, work: Path, attempts: list[dict]) -> tuple[list[dict], str]:
        providers: list[tuple[str, Callable[[], list[dict]]]] = [
            ("faster-whisper", lambda: self.faster_whisper_asr(audio, language)),
            ("whisper.cpp", lambda: self.whisper_cpp_asr(audio, language, work / "cpp")),
        ]
        if os.environ.get("NASS_ALLOW_EXTERNAL_ASR") == "1":
            providers.append(("groq-free-quota", lambda: self.groq_asr(audio, language, work / "groq")))
        for name, fn in providers:
            try:
                segments = fn()
                if not segments:
                    raise RuntimeError("ASR output empty")
                attempts.append(vars(Attempt("asr", name, True)))
                return segments, name
            except Exception as exc:
                attempts.append(vars(Attempt("asr", name, False, safe_error(exc))))
        raise RuntimeError("All speech recognizers failed; see attempts")

    def get_captions(self, video_id: str, language: str, work: Path, attempts: list[dict]) -> tuple[list[dict], str] | None:
        # Cache is a third offline-capable source. A recent track avoids fragile repeat scraping.
        cache_file = self.root / "captions-cache" / (video_id + "_" + language + ".json")
        saved = None
        try:
            saved = json.loads(cache_file.read_text("utf-8"))
            if time.time() - float(saved.get("timestamp", 0)) <= CAPTION_CACHE_SECONDS:
                segments = saved.get("segments", [])
                if segments:
                    attempts.append(vars(Attempt("captions", "local-captions-cache", True)))
                    return segments, "cache:" + saved.get("source", "captions")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            saved = None
        for name, fn in (
            ("youtube-transcript-api", lambda: self.yt_captions(video_id, language)),
            ("yt-dlp-captions", lambda: self.ytdlp_captions(video_id, language, work / "subs")),
            ("yt-transcript-go", lambda: self.go_captions(video_id, language, work / "go_subs"))):
            try:
                segments, provider = fn()
                if not segments:
                    raise RuntimeError("Empty caption result")
                attempts.append(vars(Attempt("captions", name, True)))
                try:
                    atomic_json(cache_file, {"timestamp": time.time(), "source": provider,
                                             "segments": segments})
                except OSError:
                    pass
                return segments, provider
            except Exception as exc:
                attempts.append(vars(Attempt("captions", name, False, safe_error(exc))))
        # Even expired captions are better than having no readable text.
        if isinstance(saved, dict) and saved.get("segments"):
            attempts.append(vars(Attempt("captions", "stale-captions-cache", True)))
            return saved["segments"], "stale-cache:" + saved.get("source", "captions")
        return None

    def transcribe(self, video_id: str, language: str = "ar", mode: str = "auto", *,
                   workspace: Path | None = None) -> dict:
        video_id = get_video_id(video_id)
        if mode not in ("auto", "captions", "audio", "verify"):
            raise ValueError("mode must be auto, captions, audio or verify")
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*|auto", language):
            raise ValueError("Invalid language code")
        work = workspace or (self.root / "work" / video_id)
        work.mkdir(parents=True, exist_ok=True)
        attempts: list[dict] = []
        captions = self.get_captions(video_id, language, work, attempts) if mode != "audio" else None
        if mode == "captions":
            if not captions:
                return {"ok": False, "error": "No accessible captions", "attempts": attempts}
            return {"ok": True, **Result(video_id, captions[1], captions[0], language,
                                          attempts=attempts).to_dict()}
        if mode == "auto" and captions:
            return {"ok": True, **Result(video_id, captions[1], captions[0], language,
                                          attempts=attempts).to_dict()}
        try:
            audio, audio_source = self.acquire_audio(video_id, work / "audio", attempts)
            segments, provider = self.speech_to_text(audio, language, work / "asr", attempts)
        except Exception as exc:
            if mode == "verify" and captions:
                result = Result(video_id, captions[1], captions[0], language,
                                attempts=attempts, verification={"status": "ASR unavailable", "error": safe_error(exc)})
                return {"ok": True, **result.to_dict()}
            return {"ok": False, "error": safe_error(exc), "video_id": video_id, "attempts": attempts}
        result = Result(video_id, "asr:"+provider, segments, language,
                        audio_source=audio_source, attempts=attempts)
        if mode == "verify" and captions:
            # Never conflate the captions with what was recognized from the sound.
            result.verification = {"captions_source": captions[1], "captions_segments": captions[0],
                                   "note": "Independent ASR and captions; human review needed for disagreements."}
        return {"ok": True, **result.to_dict()}

    def transcribe_file(self, name: str, language: str = "ar", workspace: Path | None = None) -> dict:
        audio = safe_input_audio(name)
        attempts = []
        try:
            self.check_audio(audio)
            segments, provider = self.speech_to_text(audio, language,
                                                      workspace or self.root / "file-asr", attempts)
            return {"ok": True, **Result("local-file", "asr:"+provider, segments,
                                          language, audio_source="authorized-local-file",
                                          attempts=attempts).to_dict()}
        except Exception as exc:
            return {"ok": False, "error": safe_error(exc), "attempts": attempts}


def health() -> dict:
    from nass_mcp import __version__
    return {"name": "Nass MCP", "version": __version__, "time": utc_now(),
            "components": {
                **{x: importlib.util.find_spec(x) is not None for x in
                   ("youtube_transcript_api", "yt_dlp", "pytubefix", "faster_whisper", "requests", "mcp")},
                **{x: shutil.which(x) is not None for x in ("ffmpeg", "ffprobe", "deno", "node", "whisper-cli", "yt-transcript", "youtubedr")},
                "youtubejs_adapter": Path(os.environ.get("NASS_YOUTUBEJS_SCRIPT", str(Path(__file__).resolve().parent / "_node" / "youtubejs_audio.mjs"))).is_file(),
                "youtubejs_package_installed": (Path(os.environ.get("NASS_YOUTUBEJS_SCRIPT", str(Path(__file__).resolve().parent / "_node" / "youtubejs_audio.mjs"))).expanduser().resolve().parent / "node_modules" / "youtubei.js").exists(),
                "whispercpp_model_configured": bool(os.environ.get("NASS_WHISPER_CPP_MODEL") and
                                                    Path(os.environ["NASS_WHISPER_CPP_MODEL"]).is_file()),
                "groq_opt_in": os.environ.get("NASS_ALLOW_EXTERNAL_ASR") == "1" and bool(os.environ.get("GROQ_API_KEY"))},
            "limits": {"max_audio_bytes": MAX_AUDIO_BYTES, "max_duration_seconds": MAX_DURATION_SEC,
                       "max_pending_jobs": JOB_QUEUE_LIMIT},
            "storage": {"data_dir": str(ROOT), "intake_dir": str(MEDIA_ROOT)}}


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(path)


class JobStore:
    """One-process bounded queue + persisted outputs; jobs after restarts are reported interrupted."""
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or Engine()
        self.base = self.engine.root / "jobs"
        self.base.mkdir(parents=True, exist_ok=True)
        self._pool = ThreadPoolExecutor(max_workers=int(os.environ.get("NASS_WORKERS", "1")))
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}

    def submit_audio_download(self, video: str) -> dict:
        return self.submit(video, "auto", "download_audio")

    def submit(self, video: str, language: str = "ar", mode: str = "auto", local: bool = False) -> dict:
        if local:
            safe_input_audio(video)
        else:
            get_video_id(video)
        if mode not in ("auto", "captions", "audio", "verify", "download_audio"):
            raise ValueError("Invalid mode")
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*|auto", language):
            raise ValueError("Invalid language")
        jobid = uuid4().hex
        job = {"job_id": jobid, "state": "queued", "created_at": utc_now(),
               "input": video, "mode": "audio" if local else mode, "language": language,
               "local": local}
        with self._lock:
            pending = sum(1 for j in self._jobs.values() if j["state"] in ("queued", "running"))
            if pending >= JOB_QUEUE_LIMIT:
                raise RuntimeError("Job queue full; retry after a job finishes")
            self._jobs[jobid] = job
            self._save(job)
        self._pool.submit(self._work, jobid)
        return job.copy()

    def _save(self, job: dict) -> None:
        atomic_json(self.base / job["job_id"] / "status.json", job)

    def _work(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["state"] = "running"
            job["started_at"] = utc_now()
            self._save(job)
        try:
            location = self.base / job_id
            if job["local"]:
                result = self.engine.transcribe_file(job["input"], job["language"], location / "work")
            elif job["mode"] == "download_audio":
                attempts: list[dict] = []
                try:
                    audio, provider = self.engine.acquire_audio(get_video_id(job["input"]),
                                                                location / "audio", attempts)
                    result = {"ok": True, "source": "raw_audio:" + provider,
                              "audio_source": provider, "file_on_server": str(audio),
                              "duration_seconds": self.engine.check_audio(audio),
                              "size_bytes": audio.stat().st_size, "attempts": attempts}
                except Exception as exc:
                    result = {"ok": False, "error": safe_error(exc), "attempts": attempts}
            else:
                result = self.engine.transcribe(job["input"], job["language"], job["mode"],
                                                workspace=location / "work")
            atomic_json(location / "result.json", result)
            next_state = "completed" if result.get("ok") else "failed"
        except Exception as exc:
            result = {"ok": False, "error": safe_error(exc)}
            atomic_json(self.base / job_id / "result.json", result)
            next_state = "failed"
        with self._lock:
            job["state"] = next_state
            job["finished_at"] = utc_now()
            job["source"] = result.get("source")
            job["attempts"] = result.get("attempts", [])
            job["error"] = result.get("error")
            self._save(job)

    def get_status(self, job_id: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid job identifier")
        status_path = self.base / job_id / "status.json"
        if not status_path.is_file():
            raise ValueError("Job not found")
        with self._lock:
            job = json.loads(status_path.read_text("utf-8"))
        if job_id not in self._jobs and job["state"] in ("queued", "running"):
            job["state"] = "interrupted"
            job["error"] = "Worker restarted before job completion; resubmit."
        return job

    def read(self, job_id: str, start_segment: int = 0, count: int = 70,
             with_timestamps: bool = True) -> dict:
        status = self.get_status(job_id)
        if status["state"] not in ("completed", "failed"):
            return {"state": status["state"], "job_id": job_id}
        path = self.base / job_id / "result.json"
        if not path.exists():
            return {"ok": False, "error": "Result not found", "job_id": job_id}
        result = json.loads(path.read_text("utf-8"))
        segments = result.pop("segments", [])
        result.pop("text", None)
        if result.get("verification"):
            verify = result["verification"]
            if "captions_segments" in verify:
                verify["caption_segment_count"] = len(verify.pop("captions_segments"))
        start_segment = max(0, start_segment)
        count = max(1, min(count, 200))
        selected = segments[start_segment:start_segment+count]
        if with_timestamps:
            result["segments"] = selected
        else:
            result["text"] = "\n".join(s["text"] for s in selected)
        result.update({"job_id": job_id, "total_segments": len(segments),
                       "next_segment": (start_segment+len(selected) if start_segment+len(selected) < len(segments) else None)})
        # Truncate only the displayed slice; reading later ranges is always possible.
        if not with_timestamps and len(result.get("text", "")) > MAX_OUTPUT_CHARS:
            result["text"] = result["text"][:MAX_OUTPUT_CHARS]
            result["warning"] = "Text clipped; request fewer segments"
        return result

    def search(self, job_id: str, query: str, max_matches: int = 15, context: int = 1) -> dict:
        """Find speech passages, returning timestamped context and a direct source link."""
        self.get_status(job_id)
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 150:
            raise ValueError("Search query must contain 1 to 150 characters")
        max_matches = max(1, min(max_matches, 50))
        context = max(0, min(context, 3))
        path = self.base / job_id / "result.json"
        if not path.is_file():
            return {"ok": False, "error": "Job result not ready"}
        result = json.loads(path.read_text("utf-8"))
        if not result.get("ok"):
            return {"ok": False, "error": "Job has no transcript"}
        segments = result.get("segments", [])
        def norm(text: str) -> str:
            # Lightweight Arabic search, no guesses about transcription accuracy.
            value = unicodedata.normalize("NFKC", text).casefold()
            value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
            return re.sub("[أإآٱ]", "ا", value).replace("ى", "ي")
        needle = norm(query.strip())
        matches = []
        total_matches = 0
        for i, seg in enumerate(segments):
            if needle in norm(seg.get("text", "")):
                total_matches += 1
                if len(matches) >= max_matches:
                    continue
                matches.append({"segment_index": i, "start": seg["start"], "end": seg["end"],
                                "text": seg["text"],
                                "context": segments[max(0, i-context):min(len(segments), i+context+1)],
                                "youtube_url": (canonical_url(result["video_id"]) + "&t=" + str(int(seg["start"])) + "s")
                                if result.get("video_id") not in (None, "local-file") else None})
        return {"ok": True, "job_id": job_id, "query": query, "matches": matches,
                "matched_count": len(matches), "total_matches": total_matches,
                "truncated": total_matches > len(matches),
                "source": result.get("source"), "is_audio_asr": result.get("is_audio_asr")}

    def make_audio_clip(self, job_id: str, start_seconds: float, duration_seconds: float = 15) -> Path:
        """Produce a short excerpt from real media for an MCP audio content block."""
        status = self.get_status(job_id)
        if not 0 <= start_seconds or not 0 < duration_seconds <= 45:
            raise ValueError("Clip must start at >=0 and last between 0 and 45 seconds")
        directory = self.base / job_id
        if status.get("local"):
            audio = safe_input_audio(status["input"])
        else:
            candidates = [p for p in directory.rglob("audio.*")
                          if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
            if candidates:
                audio = candidates[0]
            else:
                # For caption-only jobs, request the *actual audio* on demand.
                attempts: list[dict] = []
                audio, _ = self.engine.acquire_audio(get_video_id(status["input"]),
                                                      directory / "clip_source", attempts)
        total = self.engine.check_audio(audio)
        if start_seconds >= total or start_seconds + duration_seconds > total + 0.1:
            raise ValueError("Requested clip is outside the audio timeline")
        clip = directory / f"excerpt_{int(start_seconds*1000)}_{int(duration_seconds*1000)}.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", str(start_seconds),
                        "-i", str(audio), "-t", str(duration_seconds), "-vn", "-ac", "1",
                        "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(clip)],
                       timeout=120, check=True, capture_output=True)
        if not clip.exists() or not clip.stat().st_size:
            raise RuntimeError("Could not prepare requested clip")
        return clip

    def export(self, job_id: str, fmt: str = "srt") -> dict:
        self.get_status(job_id)
        if fmt not in ("srt", "txt", "json"):
            raise ValueError("format must be srt, txt or json")
        p = self.base / job_id / "result.json"
        if not p.is_file():
            return {"ok": False, "error": "Job has no output yet"}
        result = json.loads(p.read_text("utf-8"))
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        target = self.base / job_id / ("transcript." + fmt)
        if fmt == "srt":
            content = srt_text(result["segments"])
        elif fmt == "txt":
            content = result["text"]
        else:
            content = json.dumps(result, ensure_ascii=False, indent=2)
        target.write_text(content, "utf-8")
        return {"ok": True, "format": fmt, "file_on_server": str(target), "size_bytes": target.stat().st_size,
                "note": "This path is on the server, not on the ChatGPT user's device."}


def doctor_cli() -> None:
    print(json.dumps(health(), ensure_ascii=False, indent=2))
