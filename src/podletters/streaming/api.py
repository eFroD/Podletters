"""FastAPI application serving the podcast RSS feed and health endpoint.

Implements FR-06.2 (accessible on local network) and FR-06.3 (new
episodes appear within 5 minutes — we cache the feed for 60 seconds).

Endpoints:

- ``GET /rss.xml``   — podcast RSS 2.0 feed
- ``GET /cover.png`` — static podcast cover art
- ``GET /healthz``   — liveness probe
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

from podletters.storage.minio_client import MinIOClient
from podletters.streaming.rss_generator import build_feed

logger = logging.getLogger(__name__)

app = FastAPI(title="Podletters", docs_url=None, redoc_url=None)

# ── Simple in-memory feed cache ──────────────────────────────────────

_CACHE_TTL_SECONDS = 60
_feed_cache: dict[str, tuple[str, float]] = {}


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
    return xml


# ── Routes ───────────────────────────────────────────────────────────


@app.get("/rss.xml")
def rss_feed() -> Response:
    """Serve the podcast RSS feed."""
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
