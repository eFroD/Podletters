"""FastAPI application serving the podcast RSS feed, health, and metrics.

Implements FR-06.2 (accessible on local network) and FR-06.3 (new
episodes appear within 5 minutes — we cache the feed for 60 seconds).

Endpoints:

- ``GET /rss.xml``    — podcast RSS 2.0 feed
- ``GET /cover.png``  — static podcast cover art
- ``GET /healthz``    — liveness probe
- ``GET /metrics``    — Prometheus-compatible metrics
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, PlainTextResponse

from podletters.storage.minio_client import MinIOClient
from podletters.streaming.rss_generator import build_feed

logger = logging.getLogger(__name__)

app = FastAPI(title="Podletters", docs_url=None, redoc_url=None)

# ── Simple in-memory feed cache ──────────────────────────────────────

_CACHE_TTL_SECONDS = 60
_feed_cache: dict[str, tuple[str, float]] = {}

# ── Metrics counters ─────────────────────────────────────────────────

_metrics: dict[str, int | float] = {
    "rss_requests_total": 0,
    "feed_regenerations_total": 0,
}


def _get_cached_feed() -> str:
    """Return the RSS feed XML, regenerating at most once per cache TTL."""
    now = time.monotonic()
    cached = _feed_cache.get("rss")
    if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    minio = MinIOClient()
    episodes = minio.list_episode_metadata()
    xml = build_feed(episodes)
    _feed_cache["rss"] = (xml, now)
    _metrics["feed_regenerations_total"] += 1
    _metrics["episodes_total"] = len(episodes)
    return xml


# ── Routes ───────────────────────────────────────────────────────────


@app.get("/rss.xml")
def rss_feed() -> Response:
    """Serve the podcast RSS feed."""
    _metrics["rss_requests_total"] += 1
    xml = _get_cached_feed()
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/cover.png")
def cover_art() -> FileResponse | Response:
    """Serve the podcast cover image from refs/cover.png."""
    cover_path = Path("refs/cover.png")
    if not cover_path.exists():
        return Response(content="no cover art", status_code=404)
    return FileResponse(str(cover_path), media_type="image/png")


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe for container orchestration."""
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    """Prometheus-compatible metrics in text exposition format."""
    try:
        minio = MinIOClient()
        episode_count = len(minio.list_episode_metadata())
    except Exception:
        episode_count = _metrics.get("episodes_total", 0)

    try:
        from podletters.storage.episode_counter import EpisodeCounter
        counter_val = EpisodeCounter().current()
    except Exception:
        counter_val = 0

    lines = [
        "# HELP podletters_episodes_total Number of episodes in MinIO",
        "# TYPE podletters_episodes_total gauge",
        f"podletters_episodes_total {episode_count}",
        "",
        "# HELP podletters_episode_counter Current episode counter value",
        "# TYPE podletters_episode_counter counter",
        f"podletters_episode_counter {counter_val}",
        "",
        "# HELP podletters_rss_requests_total Total RSS feed requests served",
        "# TYPE podletters_rss_requests_total counter",
        f'podletters_rss_requests_total {_metrics.get("rss_requests_total", 0)}',
        "",
        "# HELP podletters_feed_regenerations_total Times the RSS feed was regenerated",
        "# TYPE podletters_feed_regenerations_total counter",
        f'podletters_feed_regenerations_total {_metrics.get("feed_regenerations_total", 0)}',
        "",
    ]
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")
