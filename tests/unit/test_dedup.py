"""Tests for podletters.ingestion.dedup."""

from __future__ import annotations

from podletters.ingestion.dedup import DEDUP_KEY, DedupStore


class FakeRedis:
    """Minimal in-memory stand-in implementing the SET ops we use."""

    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}

    def sismember(self, name: str, value: str) -> bool:
        return value in self.sets.get(name, set())

    def sadd(self, name: str, *values: str) -> int:
        bucket = self.sets.setdefault(name, set())
        added = 0
        for v in values:
            if v not in bucket:
                bucket.add(v)
                added += 1
        return added

    def scard(self, name: str) -> int:
        return len(self.sets.get(name, set()))


def test_mark_and_check() -> None:
    store = DedupStore(FakeRedis())
    assert store.is_processed("<a@x>") is False
    assert store.mark_processed("<a@x>") is True
    assert store.is_processed("<a@x>") is True
    # Second mark is a no-op
    assert store.mark_processed("<a@x>") is False
    assert store.count() == 1


def test_empty_message_id_is_not_processed() -> None:
    store = DedupStore(FakeRedis())
    assert store.is_processed("") is False
    assert store.mark_processed("") is False
    assert store.count() == 0


def test_uses_expected_key() -> None:
    fake = FakeRedis()
    store = DedupStore(fake)
    store.mark_processed("<a@x>")
    assert DEDUP_KEY in fake.sets
    assert "<a@x>" in fake.sets[DEDUP_KEY]


def test_isolated_keys() -> None:
    fake = FakeRedis()
    a = DedupStore(fake, key="ns:a")
    b = DedupStore(fake, key="ns:b")
    a.mark_processed("<id>")
    assert a.is_processed("<id>") is True
    assert b.is_processed("<id>") is False
