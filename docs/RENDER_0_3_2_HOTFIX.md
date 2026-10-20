# Nass v0.3.2 — Render actual-audio smoke-test fix

First live run (20 Oct 2026) ended with `failed`: yt-dlp default/iOS received YouTube bot wall, pytubefix received 403, YouTube.js was unable to run (npm installed in source tree instead of imported Python package), youtubedr was unavailable. These are observed failures, not successes.

Fixes: install `youtubei.js` alongside the installed Python package's `_node` script, retain safe failure classification from stderr, add a `yt-dlp/web_embedded` attempt for embeddable videos, and fix the misleading health version number. `web_embedded` availability is video-dependent; all methods can still fail on a cloud IP.

This patch requires Git push and manual Render redeploy because auto-deploy is disabled. Confirm `nass_health` reports v0.3.2 and `youtubejs_package_installed=true` before retrying short audio mode. Then inspect `nass_job_status` for audio provider success/failure. An ASR model being installed does not prove any actual audio has been transcribed.

Tests in this source archive run offline; a live YouTube success is not claimed. No YouTube cookies or paid API credentials required.
