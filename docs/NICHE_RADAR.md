# Nass MCP — Niche Provider Research (20 October 2026)

These are *candidates*, not claims of real-world reliability. The server must remain functional if none of the optional programs is installed.

| Implementation | Stage | Independence | Result |
| --- | --- | --- | --- |
| [rapha30/yt-youtube-transcript](https://github.com/rapha30/yt-youtube-transcript) | Captions | Go stdlib + ANDROID/IOS InnerTube + watch-page | Optional integrated `yt-transcript`; `-srt` output is parsed, with explicit source. InnerTube remains an undocumented provider. |
| [kkdai/youtube (youtubedr)](https://github.com/kkdai/youtube) | Audio | Native Go implementation | Optional integrated `youtubedr`; attempts AAC itag 140, which may be unavailable. Source format is independently checked with ffprobe. |
| [LuanRT/YouTube.js](https://github.com/LuanRT/YouTube.js) | Audio | JavaScript InnerTube implementation | Optional integrated Node adapter; requests MP4 audio, applies a strict byte budget while streaming, then verifies with ffprobe. Requires an explicitly installed npm package. |
| [Mithronn/rusty_ytdl](https://github.com/Mithronn/rusty_ytdl) | Audio | Rust extraction library | *Watched, not installed*: add only after confirming active YouTube coverage and repeatable CLI semantics. |
| [NewPipeExtractor](https://github.com/TeamNewPipe/NewPipeExtractor) | Audio / Video metadata | Java standalone library | *Watched, not installed*: meaningful independent logic, but requires a Java bridge and packaging/testing not yet available. |
| [FrogSnot/Sunder](https://github.com/FrogSnot/Sunder) | Music playback | Uses yt-dlp | Not added: user-facing playback application; does not add an independent extraction method. |
| [k2-fsa/sherpa-onnx SenseVoice](https://github.com/k2-fsa/sherpa-onnx) | ASR | Independent model runtime | Not an Arabic ASR option with the documented SenseVoice models (Chinese, Cantonese, English, Japanese, Korean). |
| [huggingface/distil-whisper](https://github.com/huggingface/distil-whisper) | ASR | Whisper-based model family | Not default for Arabic: project's official distilled checkpoints are oriented to English; retain standard multilingual Whisper. |

**Common-mode failure:** multiple independent libraries can still fail together if YouTube denies the host network address, video rights are restricted, or the InnerTube API changes. More libraries are not a guarantee of access.

**Release evidence:** deterministic unit tests cover adapter calls, failure transitions, video-vs-audio stream validation, and packaging. They do not assert a successful live YouTube fetch: the build container has no DNS/network access.
