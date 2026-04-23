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
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

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
        f"podletters_rss_requests_total {_metrics.get('rss_requests_total', 0)}",
        "",
        "# HELP podletters_feed_regenerations_total Times the RSS feed was regenerated",
        "# TYPE podletters_feed_regenerations_total counter",
        f"podletters_feed_regenerations_total {_metrics.get('feed_regenerations_total', 0)}",
        "",
    ]
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")


@app.get("/")
def episode_library() -> HTMLResponse:
    """Minimal episode library page listing all episodes."""
    try:
        minio = MinIOClient()
        episodes = minio.list_episode_metadata()
    except Exception:
        episodes = []

    rows = ""
    for ep in episodes:
        dur_m = ep.duration_seconds // 60
        dur_s = ep.duration_seconds % 60
        size_mb = ep.file_size_bytes / 1e6
        date = ep.created_at.strftime("%Y-%m-%d %H:%M")
        url = str(ep.file_url)
        rows += f"""
        <tr>
          <td>{ep.episode_number or "–"}</td>
          <td><a href="{url}">{ep.title}</a></td>
          <td>{ep.description}</td>
          <td>{date}</td>
          <td>{dur_m}:{dur_s:02d}</td>
          <td>{size_mb:.1f} MB</td>
          <td>{ep.source_sender}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Podletters — Episode Library</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #212529; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
    p.sub {{ color: #6c757d; margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #dee2e6; font-size: 0.9rem; }}
    th {{ background: #e9ecef; font-weight: 600; }}
    tr:hover {{ background: #f1f3f5; }}
    a {{ color: #0d6efd; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty {{ text-align: center; padding: 2rem; color: #6c757d; }}
    .links {{ margin-top: 1rem; font-size: 0.85rem; }}
    .links a {{ margin-right: 1rem; }}
  </style>
</head>
<body>
  <h1>Podletters</h1>
  <p class="sub">{len(episodes)} episode{"s" if len(episodes) != 1 else ""}</p>
  <table>
    <thead>
      <tr><th>#</th><th>Title</th><th>Description</th><th>Date</th><th>Duration</th><th>Size</th><th>Source</th></tr>
    </thead>
    <tbody>
      {rows if rows else '<tr><td colspan="7" class="empty">No episodes yet. Subscribe newsletters and wait for the pipeline to run.</td></tr>'}
    </tbody>
  </table>
  <div class="links">
    <a href="/rss.xml">RSS Feed</a>
    <a href="/metrics">Metrics</a>
    <a href="/healthz">Health</a>
  </div>
</body>
</html>"""
    return HTMLResponse(html)
