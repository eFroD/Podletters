"""Tests for podletters.storage.episode_counter."""

from __future__ import annotations

from unittest.mock import MagicMock

from podletters.storage.episode_counter import EpisodeCounter


def test_next_increments() -> None:
    fake_redis = MagicMock()
    fake_redis.incr.side_effect = [1, 2, 3]
    counter = EpisodeCounter(client=fake_redis)

    assert counter.next() == 1
    assert counter.next() == 2
    assert counter.next() == 3


def test_current_returns_zero_when_unset() -> None:
    fake_redis = MagicMock()
    fake_redis.get.return_value = None
    counter = EpisodeCounter(client=fake_redis)

    assert counter.current() == 0


def test_current_returns_value() -> None:
    fake_redis = MagicMock()
    fake_redis.get.return_value = "5"
    counter = EpisodeCounter(client=fake_redis)

    assert counter.current() == 5
