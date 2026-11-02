# Job cancellation and crash-safe persistence

Nass keeps one background worker pool per host process and writes status and
transcription results as atomically replaced JSON files.

* `nass_cancel_job(job_id)` only cancels **queued, not running** work. It
  never promises to stop an ASR computation already executing.
* `cancelled` jobs retain persisted status, have no transcript result and
  do not count toward the pending-job limit.
* Completed and failed jobs no longer occupy the in-memory active-job map.
  Their results and status remain available on disk.
* Writes use unique private temporary files, an `fsync`, and atomic replace
  within the same directory. Concurrent writers cannot clobber each other's
  temporary file.
* If the service process restarts while a job is queued/running, the old job
  is reported `interrupted` on read. **Automatic job resume is not yet
  implemented** and should not be claimed.
* One process per data directory is required. This implementation is not
  a distributed queue or a multi-host lock service.
* Preserve the data directory on a real persistent volume if durable results
  are required; free cloud workers may use ephemeral storage.

Run the tests via `python -m pytest -q`, including the concurrent write and
queue-cancellation cases in `tests/test_job_lifecycle_v05.py`.
