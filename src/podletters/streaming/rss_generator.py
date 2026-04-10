"""RSS 2.0 feed generator with iTunes podcast extensions.

Implements FR-06.1: builds a valid podcast RSS feed from the episode
metadata stored in MinIO. The feed is regenerated on each request (with
an optional cache) so new episodes appear within seconds of upload
(FR-06.3).
"""

from __future__ import annotations

import logging
from datetime import timezone

from feedgen.feed import FeedGenerator

from podletters.config import Settings, get_settings
from podletters.models import EpisodeMetadata

logger = logging.getLogger(__name__)


def _duration_str(seconds: int) -> str:
    """Format seconds as HH:MM:SS for ``<itunes:duration>``."""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_feed(
    episodes: list[EpisodeMetadata],
    settings: Settings | None = None,
) -> str:
    """Build an RSS 2.0 + iTunes feed from a list of episode metadata.

    Parameters
    ----------
    episodes:
        Episode metadata objects, typically from
        :meth:`MinIOClient.list_episode_metadata`. Should be sorted
        newest-first.
    settings:
        Pipeline settings for podcast title, author, base URL.

    Returns
    -------
    str
        The complete RSS/XML document as a UTF-8 string.
    """
    settings = settings or get_settings()

    fg = FeedGenerator()
    fg.load_extension("podcast")

    # ── Channel-level fields ──────────────────────────────────────────
    fg.title(settings.podcast_title)
    fg.link(href=settings.podcast_base_url, rel="alternate")
    fg.description(f"{settings.podcast_title} — automatisch generiert aus Newslettern.")
    fg.language("de")
    fg.generator("Podletters")

    fg.podcast.itunes_author(settings.podcast_author)
    fg.podcast.itunes_category("Technology")
    fg.podcast.itunes_explicit("no")

    cover_url = f"{settings.podcast_base_url}/cover.png"
    fg.podcast.itunes_image(cover_url)
    fg.image(url=cover_url, title=settings.podcast_title, link=settings.podcast_base_url)

    # ── Items ─────────────────────────────────────────────────────────
    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep.episode_id)
        fe.title(ep.title)
        fe.description(ep.description)

        pub_date = ep.created_at
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        fe.pubDate(pub_date)

        file_url = str(ep.file_url)
        fe.enclosure(file_url, str(ep.file_size_bytes), "audio/mpeg")

        fe.podcast.itunes_duration(_duration_str(ep.duration_seconds))
        fe.podcast.itunes_author(settings.podcast_author)
        if ep.episode_number:
            fe.podcast.itunes_episode(ep.episode_number)

    rss_xml = fg.rss_str(pretty=True).decode("utf-8")
    logger.info("Generated RSS feed: %d episodes, %d bytes", len(episodes), len(rss_xml))
    return rss_xml


__all__ = ["build_feed"]
