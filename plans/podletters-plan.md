# Plan: Newsletter-to-Podcast Pipeline (Podletters)

## Context

The repository `Podletters` is currently **empty** (no commits, no files — only a `.git` directory on branch `claude/review-podcast-prd-pdJAp`). The user has provided a comprehensive PRD (v1.0) for a fully-local, self-hosted pipeline that turns email newsletters into a German two-host podcast (IMAP → LLM transcript → F5-TTS → MP3 → MinIO → RSS), and wants a **review of the PRD plus a comprehensive, multi-session task list** for building it as a Docker Compose deployable service.

The goal of this plan is therefore not to write code, but to:
1. Capture PRD review notes / clarifications worth resolving before coding.
2. Define the repository skeleton.
3. Break the work into small, ordered, multi-session-friendly tasks grouped by the PRD's 5 phases, so future sessions can pick up where previous ones left off.

## PRD Review Notes

Overall the PRD is solid and implementation-ready. Points worth deciding before/while coding:

- **GPU sharing (OQ-01):** Ollama keeps the model resident. To honor NFR-04 (≤24 GB, sequential), the LLM task should call Ollama's `/api/generate` with `keep_alive: 0` (or POST `/api/chat` then unload) before F5-TTS loads. Worth making this explicit in `ollama_client.py`.
- **Streaming layer (OQ-02):** AzuraCast is heavy for a single-user on-demand podcast. Recommend starting with a **minimal FastAPI RSS + static MinIO URLs** in Phase 3, treating AzuraCast as optional later. This also simplifies docker-compose.
- **F5-TTS German quality:** F5-TTS is primarily English/Chinese. German zero-shot works but quality varies. Plan should include a **TTS smoke-test task early in Phase 1** to validate before committing — fallback option: XTTS-v2 (Coqui) which has stronger German.
- **Concurrency:** `worker_prefetch_multiplier=1` plus a **single Celery worker with one queue** is simpler than splitting LLM/TTS queues for v1. Revisit only if needed.
- **Dedup store:** PRD says "Redis or SQLite". Redis is already required for Celery → use Redis SET for `processed_message_ids` to avoid a second datastore.
- **Secrets:** `.env` is fine for local; ensure `.env` is gitignored and only `.env.example` committed.
- **Cover art / podcast image:** Needed for iTunes RSS validity — add a placeholder PNG to `refs/`.
- **Episode numbering:** PRD mentions it in Phase 4 — store a monotonically increasing counter in Redis.

## Repository Layout (target)

Matches PRD §18.D, with additions for Docker:

```
Podletters/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile.worker          # Celery worker (LLM+TTS, GPU)
├── Dockerfile.api             # FastAPI RSS server
├── pyproject.toml             # uv / poetry
├── README.md
├── refs/
│   ├── host1.wav
│   ├── host2.wav
│   └── cover.png
├── src/podletters/
│   ├── __init__.py
│   ├── config.py              # pydantic-settings
│   ├── ingestion/{imap_client.py, text_cleaner.py, dedup.py}
│   ├── llm/{ollama_client.py, prompt.py, parser.py}
│   ├── tts/{f5tts_renderer.py, audio_merger.py}
│   ├── postprocessing/normalize.py
│   ├── storage/minio_client.py
│   ├── streaming/{rss_generator.py, api.py}
│   ├── models.py              # Pydantic NewsletterPayload, TranscriptPayload, EpisodeMetadata
│   ├── tasks.py               # Celery tasks
│   └── celery_app.py
└── tests/
    ├── unit/
    └── integration/
```

## Comprehensive Task List

Tasks are sized to fit a single coding session each (~30–90 min). `[S]` = self-contained, `[D]` = depends on prior task.

### Phase 0 — Project Bootstrap

1. **[S] Repo scaffolding**: create `pyproject.toml` (uv or poetry), `.gitignore`, `README.md` stub, `src/podletters/` package, empty `__init__.py`, `.env.example` from PRD §15.
2. **[S] Pydantic settings**: implement `src/podletters/config.py` loading every variable in PRD §15 with validation.
3. **[S] Pydantic models**: implement `models.py` (`NewsletterPayload`, `TranscriptSegment`, `TranscriptPayload`, `EpisodeMetadata`) matching PRD §5.1, §5.2, §5.5.
4. **[D] Docker Compose skeleton**: `docker-compose.yml` with services `redis`, `minio`, `ollama`, `worker`, `api`. Use `nvidia` runtime + `deploy.resources.reservations.devices` for GPU on `worker` (and `ollama`). Volumes for `refs/`, MinIO data, Ollama models.
5. **[D] Dockerfiles**: `Dockerfile.worker` (CUDA base, ffmpeg, Python deps incl. F5-TTS), `Dockerfile.api` (slim Python, FastAPI). Document expected GPU base image.
6. **[D] Makefile / justfile**: targets `up`, `down`, `logs`, `worker-shell`, `test`, `lint`, `format`.

### Phase 1 — Core Pipeline (MVP, manual trigger)

7. **[D] IMAP client**: `ingestion/imap_client.py` using `imap-tools` — fetch unseen, filter by `SENDER_WHITELIST`, return raw `email.message.EmailMessage` list. (FR-01.1, FR-01.2, FR-01.5)
8. **[D] HTML/text cleaner**: `ingestion/text_cleaner.py` using `trafilatura` (fallback `html2text`) — strip footers, tracking pixels, unsubscribe links. Unit-tested with 2–3 saved real newsletter `.eml` fixtures. (FR-01.4)
9. **[D] Dedup store**: `ingestion/dedup.py` — Redis SET-based `is_processed(msg_id)` / `mark_processed(msg_id)`. (FR-01.3)
10. **[D] Ingestion smoke test**: CLI script `python -m podletters.ingestion.imap_client` that prints first cleaned newsletter — validates Phase 1 step 1 manually.
11. **[D] Ollama client**: `llm/ollama_client.py` — `chat(messages, model, timeout, keep_alive=0)` via `httpx`; explicit unload after call.
12. **[D] Prompt module**: `llm/prompt.py` — system + user templates exactly as PRD §12.1.
13. **[D] LLM output parser**: `llm/parser.py` — parser from PRD §12.2; raises on missing TITLE/DESCRIPTION/`---`. Unit tests with sample LLM outputs (happy path + malformed).
14. **[D] LLM smoke test**: CLI that takes a newsletter `.eml`, runs ingestion → Ollama → parser, prints `TranscriptPayload` JSON. Validates German quality of Qwen2.5-32B (OQ-07).
15. **[D] F5-TTS renderer**: `tts/f5tts_renderer.py` — load model once, `render_segment(text, ref_audio, ref_text) -> (np.ndarray, sr)`. Document VRAM behavior.
16. **[S] Reference voices**: Piper bootstrap script (PRD §11) that generates `refs/host1.wav` + `refs/host2.wav`; also commit a placeholder `cover.png`.
17. **[D] Audio merger**: `tts/audio_merger.py` — concatenate segments with `SEGMENT_SILENCE_MS` padding using `numpy`. (FR-03.3, FR-03.4)
18. **[D] TTS smoke test**: CLI that takes parsed `TranscriptPayload` JSON and writes a raw WAV. **Validates F5-TTS German quality before committing further.** Fallback decision point → XTTS-v2.
19. **[D] Loudness normalization + MP3 encode**: `postprocessing/normalize.py` — `pyloudnorm` to −16 LUFS, true peak −1 dBTP, then `pydub`/`ffmpeg` → 128 kbps MP3 with ID3 tags. (FR-04.1–04.3)
20. **[D] End-to-end manual MVP script**: `scripts/run_pipeline.py` — wires steps 7→19 sequentially without Celery, writes MP3 to `./out/`. **Phase 1 DoD = listenable MP3.**

### Phase 2 — Automation & Storage

21. **[D] Celery app**: `celery_app.py` with Redis broker/backend, `worker_prefetch_multiplier=1`, `task_acks_late=True`.
22. **[D] Task: `ingest_email_task`** — wraps step 7+8+9, enqueues per newsletter.
23. **[D] Task: `generate_transcript_task`** — wraps Ollama call + parser.
24. **[D] Task: `render_audio_task`** — wraps F5-TTS render + merge. Ensures Ollama unloaded first.
25. **[D] Task: `postprocess_audio_task`** — normalize + MP3.
26. **[D] Celery Beat schedule**: poll IMAP every `POLL_INTERVAL_SECONDS`. (FR-07.1)
27. **[D] Retry policy**: `autoretry_for`, `retry_backoff=True`, `max_retries=3`, dead-letter handling. (FR-07.2, NFR-06)
28. **[D] MinIO client**: `storage/minio_client.py` with `boto3` — `upload_episode(mp3_path, metadata)` writing both `.mp3` and `.json` to `YYYY/MM/` keys. (FR-05.1–05.3)
29. **[D] Task: `upload_episode_task`** + chain wiring (`chain(...)` or `link=`).
30. **[D] Structured logging**: JSON logger (stdlib `logging` + `python-json-logger`) used by every task with `task_id`, `episode_id`, `stage`, `duration_ms`. (NFR-07)
31. **[D] Phase 2 integration test**: drop a fixture `.eml` into a fake mailbox dir → confirm episode appears in MinIO.

### Phase 3 — Streaming & Discovery

32. **[D] RSS generator**: `streaming/rss_generator.py` — builds RSS 2.0 + iTunes feed by listing MinIO `*.json` metadata objects. (PRD §13.4, FR-06.1)
33. **[D] FastAPI service**: `streaming/api.py` — `GET /rss.xml`, `GET /healthz`, `GET /cover.png`. Reads MinIO each request (cache 60 s). (FR-06.2, FR-06.3)
34. **[D] Compose wiring for `api`**: expose port 8080, env vars, depends_on MinIO.
35. **[D] Podcast client validation**: manual test with AntennaPod & Pocket Casts on LAN; document IP setup in README.

### Phase 4 — Quality & Polish

36. **[S] Dynamic range compression** between speakers (ffmpeg `acompressor` filter) — toggle in config.
37. **[D] Prompt iteration**: evaluate output on 10 real newsletters, refine system prompt, snapshot results in `tests/fixtures/prompt_eval/`.
38. **[S] Episode numbering**: Redis counter, surfaced in MP3 ID3 tag and RSS `<itunes:episode>`.
39. **[S] Better reference voices**: documented procedure for higher-quality refs (recorded or curated).
40. **[S] Cover art**: replace placeholder, embed in MP3 + reference in feed.

### Phase 5 — Observability & Maintenance (Optional)

41. **[S] systemd unit files** as alternative to compose for bare-metal.
42. **[S] Prometheus metrics endpoint** in FastAPI + Celery exporter.
43. **[S] Minimal episode-library web UI** (Jinja template listing JSON metadata).
44. **[S] Retention policy task** (Celery Beat job to delete episodes older than N days).

## Critical Files (to be created)

- `docker-compose.yml`, `Dockerfile.worker`, `Dockerfile.api`
- `src/podletters/config.py`, `models.py`, `celery_app.py`, `tasks.py`
- `src/podletters/ingestion/{imap_client,text_cleaner,dedup}.py`
- `src/podletters/llm/{ollama_client,prompt,parser}.py`
- `src/podletters/tts/{f5tts_renderer,audio_merger}.py`
- `src/podletters/postprocessing/normalize.py`
- `src/podletters/storage/minio_client.py`
- `src/podletters/streaming/{rss_generator,api}.py`
- `.env.example`, `refs/host1.wav`, `refs/host2.wav`, `refs/cover.png`

(No existing functions to reuse — repository is empty.)

## Verification

- **Phase 1 DoD:** `python scripts/run_pipeline.py path/to/newsletter.eml` produces a listenable German MP3 in `./out/`.
- **Phase 2 DoD:** `docker compose up` → drop a real newsletter into the configured mailbox → within 15 min, MP3+JSON appear in MinIO bucket `podcast-episodes/YYYY/MM/`. Verify via `mc ls` or MinIO console at `:9001`.
- **Phase 3 DoD:** `curl http://<host>:8080/rss.xml` returns valid RSS; AntennaPod subscription on LAN successfully streams the latest episode.
- **Tests:** `pytest tests/unit` for parsers/cleaner; `pytest tests/integration` (marked, optional, requires running compose stack) for the end-to-end task chain using a fixture `.eml`.
- **NFR-04 check:** `nvidia-smi` during a run shows peak ≤ 22 GB and no overlap between Ollama and F5-TTS phases.
