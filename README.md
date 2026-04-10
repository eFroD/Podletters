# Podletters

Local, self-hosted newsletter-to-podcast pipeline. Ingests email newsletters,
generates a German two-host dialogue via a local LLM (Ollama + Qwen2.5),
renders audio with F5-TTS, and exposes episodes through an RSS feed.

See `plans/podletters-plan.md` for the full implementation plan.

## Quick Start

```bash
cp .env.example .env        # edit with your IMAP credentials + sender whitelist
make bootstrap-voices        # generate reference WAV clips (requires piper-tts)
make up                      # start all services
make logs                    # tail output
```

## RSS Feed / Podcast Client Setup

Once `make up` is running the RSS feed is available at:

```
http://<your-lan-ip>:8080/rss.xml
```

### AntennaPod / Pocket Casts

1. Find your host's LAN IP (`ip addr` or `hostname -I`).
2. In your podcast app choose **Add podcast by URL / RSS**.
3. Enter `http://<ip>:8080/rss.xml`.
4. Episodes should appear within 60 seconds of upload to MinIO.

### Troubleshooting

- **Feed empty?** Check that the worker has processed at least one newsletter
  (`make logs | grep upload`).
- **App can't reach feed?** Ensure your phone is on the same LAN and that
  port 8080 is not firewalled on the host.
- **Audio URLs 404?** MinIO must be reachable from the podcast client. Set
  `PODCAST_BASE_URL` in `.env` to `http://<ip>:9000`.

## Makefile Targets

```
make help              # list all targets
make up / down / logs  # docker compose lifecycle
make run-pipeline      # end-to-end MVP (IMAP → LLM → TTS → MP3)
make smoke-ingest      # test IMAP fetch + text cleaning
make smoke-llm         # test Ollama transcript generation
make smoke-tts         # test F5-TTS audio rendering
make bootstrap-voices  # generate Piper reference clips
make test / lint       # pytest + ruff inside the worker container
```

## Status

Phase 3 complete — RSS feed + streaming.
