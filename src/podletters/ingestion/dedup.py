"""Redis-backed dedup store for processed Message-IDs.

Implements FR-01.3: a newsletter that has already been turned into an
episode must never be reprocessed. We reuse the Redis instance that
already exists for the Celery broker rather than introducing a second
datastore.
"""

from __future__ import annotations

import logging
from typing import Protocol

import redis

from podletters.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEDUP_KEY = "podletters:processed_message_ids"


class _RedisLike(Protocol):
    def sismember(self, name: str, value: str) -> int | bool: ...
    def sadd(self, name: str, *values: str) -> int: ...
    def scard(self, name: str) -> int: ...


class DedupStore:
    """Simple SET-based dedup keyed on RFC 5322 ``Message-ID``."""

    def __init__(self, client: _RedisLike, key: str = DEDUP_KEY) -> None:
        self._client = client
        self._key = key

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "DedupStore":
        settings = settings or get_settings()
        client = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
        return cls(client)

    def is_processed(self, message_id: str) -> bool:
        if not message_id:
            return False
        return bool(self._client.sismember(self._key, message_id))

    def mark_processed(self, message_id: str) -> bool:
        """Add ``message_id`` to the set. Returns ``True`` if newly added."""
        if not message_id:
            logger.debug("Refusing to mark empty message_id as processed")
            return False
        added = self._client.sadd(self._key, message_id)
        return bool(added)

    def count(self) -> int:
        return int(self._client.scard(self._key))


__all__ = ["DedupStore", "DEDUP_KEY"]
