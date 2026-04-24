# Podletters — Senior Code Review

**Reviewer:** Senior Engineering Review
**Date:** 2026-04-24
**Branch:** `claude/code-review-document-rJGdX`
**Scope:** Full codebase — `src/`, `tests/`, `scripts/`, `deploy/`, Docker/Compose, config
**Status at review:** Phase 3 complete (RSS feed + streaming)

---

## 1. Project Summary

Podletters is a self-hosted pipeline that turns email newsletters into a German two-host podcast. The stack:

- **Ingestion:** IMAP polling (`imap-tools`) with sender whitelist, RFC 5322 Message-ID dedup via Redis SET, HTML cleaning via `trafilatura` + `html2text`.
- **LLM:** Ollama HTTP API (Qwen2.5 32B q4) producing structured `TITLE / DESCRIPTION / --- / [HOST1]/[HOST2]` output.
- **TTS:** F5-TTS zero-shot voice cloning with per-speaker reference WAV/text; lazy load + explicit unload for VRAM management.
- **Post-processing:** `pyloudnorm` LUFS normalization, compression, true-peak limiting, MP3 encode with `mutagen` ID3 tags and cover art.
- **Storage:** MinIO S3 (`boto3`) with date-prefixed keys and JSON sidecars; monotonic Redis episode counter.
- **Delivery:** FastAPI exposes `/rss.xml` (built via `feedgen` with iTunes extensions), `/metrics`, `/`.
- **Orchestration:** Celery on Redis, beat schedule for IMAP poll, `concurrency=1` for GPU serialization, `acks_late=True`.
- **Deployment:** Docker Compose (redis, minio, ollama, worker, api) + systemd units with hardening.

Overall, the codebase is clean, well-typed, well-tested at unit level, and thoughtfully structured. The issues below are the gap between a working Phase 3 MVP and a production deployment.

---

## 2. Issue Index

| ID  | Severity  | Area            | Title                                                              |
| --- | --------- | --------------- | ------------------------------------------------------------------ |
| C1  | Critical  | Tasks           | Non-listed exceptions silently fail the pipeline                   |
| C2  | Critical  | Security        | Default MinIO credentials in `.env.example` (`minioadmin`)         |
| C3  | Critical  | Tasks           | Task inputs (`prev_result`) unpacked without validation            |
| H1  | High      | Storage         | `delete_episode` uses substring match — collateral deletion risk   |
| H2  | High      | Ingestion       | Emails that raise in `to_payload` are never marked processed       |
| H3  | High      | Concurrency     | Episode counter race / duplicate numbering under retry             |
| H4  | High      | API             | `/metrics` swallows all exceptions, no CORS/rate limit/auth        |
| H5  | High      | Worker infra    | `Dockerfile.worker` has no HEALTHCHECK                             |
| H6  | High      | Filesystem      | `/tmp` WAVs leak on failure between `render` and `postprocess`     |
| M1  | Medium    | API             | In-process `_feed_cache` and `_metrics` are not shared or invalidated |
| M2  | Medium    | Config          | Hardcoded `refs/cover.png` relative path                           |
| M3  | Medium    | RSS             | Title/description not HTML-escaped before feed/ID3                 |
| M4  | Medium    | Reliability     | No retry jitter — thundering herd on outage recovery               |
| M5  | Medium    | Reliability     | No graceful-shutdown handler for SIGTERM (in-flight work, VRAM)    |
| M6  | Medium    | IMAP            | No distinction between auth failures and transient network errors  |
| L1  | Low       | Types           | `# type: ignore[union-attr]` on `F5TTS.infer` hides Optional model |
| L2  | Low       | Supply chain    | No lock file / no vulnerability scan in CI                         |
| L3  | Low       | Observability   | No Prometheus/tracing; `/metrics` is hand-rolled plaintext         |
| L4  | Low       | Redis           | No documented key namespace / schema version                       |
| L5  | Low       | Docs            | LAN-bind expectations not documented as a firewall requirement     |

---

## 3. Critical Issues

### C1 — Unhandled exception types fail tasks silently
**Files:** `src/podletters/tasks.py` (every `@app.task` with `autoretry_for=(...)`)

`autoretry_for` retries only the listed exception types. Pydantic `ValidationError`, `KeyError`, `AttributeError`, `TranscriptParseError`, etc., fall outside the tuple and either crash the task with no retry or propagate as an un-handled failure, leaving the chain half-done (orphan temp files, no MinIO upload, no log correlation).

**Fix:**
- Wrap each task body in `try/except`, split expected transient errors (network, IMAP, Ollama 5xx) from permanent errors (validation, parse).
- Transient → `self.retry(exc=exc, countdown=...)`.
- Permanent → log with `logger.exception`, write a failure record to MinIO or Redis, then `return`/`raise Reject(requeue=False)` so the chain short-circuits cleanly.
- Consider a dead-letter stream (`podletters:dead_letter`) Redis list keyed by Message-ID for later inspection.

### C2 — Default MinIO credentials committed
**File:** `.env.example` lines 29–30
```
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```
Widely-known defaults. A user who copies the example and exposes port 9000 on their LAN or router gets a fully writable S3 bucket accessible to any device on the network.

**Fix:**
- Replace both values with `CHANGE_ME` sentinels.
- Add a `@field_validator` in `config.py` that rejects `minioadmin` / `CHANGE_ME` at startup.
- Document key rotation and use `mc admin user add` rather than the root credentials for worker/API service accounts (least privilege: worker needs PutObject, API needs GetObject/ListObjects only).

### C3 — Task inputs not validated at chain boundaries
**File:** `src/podletters/tasks.py` — `render_audio`, `postprocess_audio`, `upload_episode`

Each downstream task does `TranscriptPayload(**prev_result["transcript"])` or similar, trusting the shape from the previous task. A serialization bug, partial retry, or manual `apply_async` with a wrong payload raises `ValidationError`, which — per C1 — is not in `autoretry_for`.

**Fix:**
- Introduce a typed helper: `def _unwrap(cls, d, key) -> T: …` that `logger.exception`s a clear error, writes the raw payload to the dead-letter store, and raises `Reject(requeue=False)`.
- Add an integration test that feeds each task a malformed `prev_result` and asserts the chain terminates without hanging workers.

---

## 4. High Issues

### H1 — `MinIOClient.delete_episode` substring match
**File:** `src/podletters/storage/minio_client.py:114` — confirmed verbatim:
```python
if slug in key:
    self._s3.delete_object(Bucket=self._bucket, Key=key)
```
If `metadata.episode_id == "2026-04"`, this also deletes `2026-04-07-foo.mp3`. Ticking bomb for any future retention job built on this primitive.

**Fix:** build the exact expected key set:
```python
expected = {f"{prefix}/{slug}.mp3", f"{prefix}/{slug}.json"}
if key in expected:
    ...
```
Add a unit test with two episode IDs where one is a prefix of the other.

### H2 — Invalid emails re-fetched forever
**File:** `src/podletters/tasks.py` `ingest_email` — on `ValueError` from `to_payload`, the email is skipped but never added to the dedup set. The next poll re-fetches the same IMAP message (it was marked `seen`, but the dedup key is what guards LLM work). Either:
- call `dedup.mark_processed(message_id)` in the `except` branch, or
- only mark_processed on successful enqueue and rely on IMAP `seen` to avoid refetch — but `seen` can be cleared by other clients, so the first option is safer.

### H3 — Episode counter duplication under concurrency / retries
**File:** `src/podletters/storage/episode_counter.py` + `tasks.py` `upload_episode`

`Redis INCR` itself is atomic. The real risk is calling `next()` inside `upload_episode` before the MP3 upload succeeds: a retry re-calls `.next()` and burns a second number, producing gaps and in some failure modes (pre-retry crash after `.next()` but before `put_object`) duplicate numbers if the operator manually re-queues. With `concurrency=1` this is unlikely today, but raising concurrency later will expose it.

**Fix:**
- Reserve the number once at chain build time and thread it through the payload.
- Or compute a deterministic episode number from `(year, monotonic per-year index)` stored in Redis HSET keyed by year.
- Log the assigned number at INFO so forensic correction is possible.

### H4 — API exposure
**File:** `src/podletters/streaming/api.py`
- `/metrics` uses bare `except Exception:` with no logging; MinIO outages look identical to "zero episodes".
- No CORS config, no rate limiting, no auth. Binds `0.0.0.0:8080` per compose config.

**Fix:**
- Narrow exception handling, log at WARNING with the exception, and set a `metrics_degraded` gauge.
- Add `slowapi` limits on `/rss.xml` and `/metrics`.
- Optional basic-auth or a static bearer token controlled by `.env` (`API_READ_TOKEN`).
- Document that the recommended deployment binds `127.0.0.1` + reverse proxy, or a trusted LAN subnet via firewall.

### H5 — Worker has no healthcheck
**File:** `Dockerfile.worker`

Compose can't detect a stuck/crashed worker. Add:
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD celery -A podletters.celery_app inspect ping -d celery@$HOSTNAME | grep -q pong || exit 1
```
And surface it in `docker-compose.yml` so `depends_on: worker: condition: service_healthy` works for future services.

### H6 — Temp WAV lifecycle
**File:** `src/podletters/tasks.py` `render_audio` / `postprocess_audio`

`NamedTemporaryFile(delete=False, dir="/tmp")` followed by `unlink(missing_ok=True)` in a later task leaks on any exception between the two stages or on chain cancellation. Hardcoded `/tmp` also makes it impossible to mount a RAM-disk or override in systemd.

**Fix:**
- Use `tempfile.mkdtemp(prefix="podletters-", dir=settings.tmp_dir)` per episode; pass the directory forward; remove it in a `finally` in `upload_episode` **and** in a periodic sweeper task that nukes directories older than N hours.
- Add `PODLETTERS_TMP_DIR` to `.env.example` and `config.py`.

---

## 5. Medium Issues

### M1 — Feed cache is per-process
`_feed_cache` and `_metrics` are module-level dicts. Under multiple uvicorn workers, each has its own cache; worse, `_metrics` is only updated when `_get_cached_feed` runs, so `/metrics` can lag for minutes.

**Fix:** move the cache to Redis (`SETEX podletters:rss 60 <xml>`). Have `upload_episode` `DEL` that key on successful upload to force immediate freshness.

### M2 — Hardcoded `refs/cover.png`
`normalize.py` and `api.py` use the relative path `refs/cover.png`. Works because compose sets the workdir; it will silently produce cover-less MP3s if anything changes cwd.

**Fix:** resolve via `pathlib.Path(__file__).resolve().parents[2] / "refs" / "cover.png"` or, better, a `COVER_ART_PATH` setting. Validate extension is `.png/.jpg/.jpeg`.

### M3 — RSS/ID3 injection surface
LLM output flows into `<title>` / `<description>` and ID3 `TIT2`/`COMM`. `feedgen` escapes XML, but ID3 does not, and a malicious or hallucinated title containing control characters can break some podcast clients. Sanitize at the boundary (`html.escape`, strip control chars, cap length).

### M4 — No retry jitter
All tasks use `retry_backoff=True, retry_backoff_max=600` without `retry_jitter=True`. When Ollama or MinIO recovers from a multi-minute outage, every pending task retries on the same second — a thundering herd on a GPU-serialized worker is particularly painful. Add `retry_jitter=True` to each `@app.task` decorator.

### M5 — No graceful shutdown
`celery_app.py` and `api.py` don't install SIGTERM handlers. On compose restart or node drain: an in-flight render can leak VRAM (F5-TTS model never `unload()`ed) and abandon a temp dir.

**Fix:** FastAPI — register a `shutdown` event that closes the MinIO client / flushes logs. Celery — rely on `worker_shutdown` signal to call `F5TTSRenderer.unload()` if any instance is live, and drain temp dirs.

### M6 — IMAP error classification
`imap_client.py` treats all errors as retryable. Invalid credentials, OAuth token expiry, and quota errors should alert loudly (critical log + optional Slack/email hook) and stop retrying with a short backoff to avoid account lockout.

---

## 6. Low Issues

### L1 — `# type: ignore[union-attr]` in F5-TTS renderer
**File:** `src/podletters/tts/f5tts_renderer.py:114`
Lazy-loaded model is `Optional[F5TTS]`. Rather than ignoring, guard with `assert self._model is not None, "load() not called"` so the error surfaces cleanly.

### L2 — No lock file / no dep scanning
`pyproject.toml` pins `>=X.Y` only. Add a `uv.lock` (or `pip-tools` compiled `requirements.txt`), enable Dependabot, and run `pip-audit` in CI.

### L3 — Observability
`/metrics` is a hand-rolled plaintext endpoint. Switch to `prometheus_client` and expose counters/histograms for: emails ingested, LLM latency, TTS seconds rendered, MinIO upload bytes, task retry counts. Consider OpenTelemetry for chain tracing (episode-id as the trace correlator).

### L4 — Redis key schema undocumented
Add a short `docs/redis.md` listing every key, value type, TTL, producer, and consumer. Version it (`podletters:v1:...`) so future refactors can migrate instead of guess.

### L5 — LAN-bind assumption in README
README says "any podcast app on the same LAN" but the service binds `0.0.0.0`. Add a firewall / reverse-proxy paragraph and call out that `PODCAST_BASE_URL` must be reachable from the playback device.

---

## 7. Test Coverage Gaps

Unit coverage is strong for pure functions (parser, cleaner, rss_generator, normalize, audio_merger). Gaps to fill:

- **Task chain integration:** exercise `ingest → transcript → render → postprocess → upload` with fakes for Ollama/F5-TTS/MinIO and assert on retry behavior, dead-letter paths, and temp-dir cleanup.
- **Failure-mode tests:**
  - `delete_episode` with a colliding prefix ID (H1 regression test).
  - `ingest_email` with a whitelisted sender whose body cleans to empty (H2).
  - `upload_episode` retried twice — counter should not skip silently (H3).
- **API error paths:** MinIO down → `/metrics` returns a documented degraded payload; `/rss.xml` returns stale cache with a header.
- **MinIOClient:** permission errors, missing bucket at startup (should `make_bucket` idempotently), object listing with >1000 keys (pagination).
- **Config validation:** reject `minioadmin` default; reject invalid sample rates already covered — add one for empty `SENDER_WHITELIST`.
- **Smoke scripts** (`scripts/run_pipeline.py`, `eval_prompt.py`) — at minimum a `--dry-run` path that unit-testable.

No load tests. A single `locust` or `k6` scenario that hammers `/rss.xml` would validate the cache story (M1).

---

## 8. Deployment / Ops Concerns

- **Compose:** Ollama container has no volume cleanup policy; model pulls accrete over time. Document `docker volume prune` or pin a model-cache size.
- **Systemd units:** good hardening. Missing `TimeoutStopSec=` tuned for in-flight renders (default 90s can kill a 3-minute F5-TTS segment).
- **Logging:** JSON logs go to stdout (good). Add a log-rotation note for the `--log-opt max-size` in compose; currently unspecified means unbounded json-file logs on long-running hosts.
- **Backups:** no documented strategy for MinIO or Redis. Episodes are regenerable but the dedup set and episode counter are not — losing them causes reprocessing of every historical email and counter reset. Add a simple `redis-cli --rdb` + `mc mirror` cron to the systemd deploy notes.
- **GPU:** no fallback if CUDA is unavailable. F5-TTS will attempt CPU which is effectively unusable. Add a startup check and fail fast with a clear error.

---

## 9. Recommended TODOs (prioritized)

**Must do before "1.0":**
1. C1 — uniform task exception handling + dead-letter store. *(tasks.py refactor, +tests)*
2. C2 — strip default MinIO credentials from `.env.example`, add config validator. *(1-file change + config validator test)*
3. C3 — typed `_unwrap` helper at chain boundaries. *(tasks.py, +tests)*
4. H1 — exact-match deletion in `MinIOClient.delete_episode` + regression test.
5. H2 — mark `ValueError` emails as processed in `ingest_email`.
6. H5 — add worker HEALTHCHECK and wire `depends_on` accordingly.
7. H6 — temp-dir lifecycle: per-episode mkdtemp, sweeper task, `PODLETTERS_TMP_DIR` env.

**Should do next:**
8. H3 — assign episode number once and thread through payload.
9. H4 — narrow `/metrics` exception handling; add `slowapi` rate limit; optional bearer token.
10. M1 — Redis-backed feed cache with explicit invalidation on upload.
11. M3 — sanitize LLM-derived strings before RSS/ID3.
12. M4 — `retry_jitter=True` on every task.
13. M5 — SIGTERM handlers in worker + FastAPI.

**Nice to have:**
14. L2 — lock file + Dependabot + `pip-audit` in CI.
15. L3 — `prometheus_client` + optional OTEL tracing.
16. L4 — `docs/redis.md` with versioned namespace.
17. Load test for `/rss.xml` + MinIO listing at >1k episodes.

---

## 10. What the Codebase Does Well

- Clear domain decomposition: `ingestion / llm / tts / postprocessing / storage / streaming`.
- Immutable, typed payloads (`frozen=True` Pydantic models, `Literal` speaker tags).
- Thoughtful VRAM management (Ollama `keep_alive=0`, F5-TTS explicit unload).
- Proper Celery semantics for GPU serialization (`concurrency=1`, `acks_late=True`).
- Loudness pipeline follows broadcast convention (-16 LUFS target, -1 dBTP ceiling).
- Testable boundaries: protocols for dedup, injected clients for IMAP/Ollama/MinIO.
- Structured JSON logging with noise reduction for boto/urllib3.
- Systemd hardening (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths`).

The foundation is solid; the items above are the delta to a production-grade self-hosted service rather than rework.
