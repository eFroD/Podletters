"""Monotonically increasing episode counter stored in Redis.

Provides a global sequence number for episodes so they can carry an
``<itunes:episode>`` tag and an ID3 track number. The counter lives
alongside the dedup SET in the Celery broker Redis instance.
"""

from __future__ import annotations

import logging

import redis

from podletters.config import get_settings

logger = logging.getLogger(__name__)

COUNTER_KEY = "podletters:episode_counter"


class EpisodeCounter:
    """Redis INCR-based counter."""

    def __init__(self, client: redis.Redis | None = None, key: str = COUNTER_KEY) -> None:
        if client is None:
            settings = get_settings()
            client = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
        self._client = client
        self._key = key

    def next(self) -> int:
        """Return the next episode number (1-based, never resets)."""
        num = int(self._client.incr(self._key))
        logger.debug("Episode counter: %d", num)
        return num

    def current(self) -> int:
        """Return the current counter value without incrementing."""
        val = self._client.get(self._key)
        return int(val) if val else 0


__all__ = ["EpisodeCounter"]
