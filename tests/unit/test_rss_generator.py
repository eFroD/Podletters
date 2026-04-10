"""Tests for podletters.streaming.rss_generator."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from types import SimpleNamespace

from podletters.models import EpisodeMetadata
from podletters.streaming.rss_generator import build_feed


def _settings():
    return SimpleNamespace(
        podcast_title="Test Podcast",
        podcast_author="Tester",
        podcast_base_url="http://localhost:9000",
    )


def _episode(
    episode_id: str = "20260407-test",
    title: str = "Test Episode",
    duration: int = 300,
) -> EpisodeMetadata:
    return EpisodeMetadata(
        episode_id=episode_id,
        title=title,
        description="A test episode.",
        source_sender="test@localhost",
        duration_seconds=duration,
        file_size_bytes=500_000,
        file_url=f"http://localhost:9000/podcast-episodes/2026/04/{episode_id}.mp3",
        created_at=datetime(2026, 4, 7, 9, 0, tzinfo=timezone.utc),
        transcript_segments=10,
    )


def test_build_feed_returns_valid_rss() -> None:
    xml_str = build_feed([_episode()], settings=_settings())
    root = ET.fromstring(xml_str)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"


def test_feed_contains_channel_metadata() -> None:
    xml_str = build_feed([], settings=_settings())
    root = ET.fromstring(xml_str)
    channel = root.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "Test Podcast"
    assert channel.findtext("language") == "de"


def test_feed_contains_episode_items() -> None:
    eps = [_episode("ep1", "First"), _episode("ep2", "Second")]
    xml_str = build_feed(eps, settings=_settings())
    root = ET.fromstring(xml_str)
    items = root.findall(".//item")
    assert len(items) == 2
    titles = [item.findtext("title") for item in items]
    assert "First" in titles
    assert "Second" in titles


def test_enclosure_has_correct_attributes() -> None:
    xml_str = build_feed([_episode()], settings=_settings())
    root = ET.fromstring(xml_str)
    enc = root.find(".//enclosure")
    assert enc is not None
    assert enc.attrib["type"] == "audio/mpeg"
    assert enc.attrib["length"] == "500000"
    assert enc.attrib["url"].endswith(".mp3")


def test_itunes_duration_format() -> None:
    xml_str = build_feed([_episode(duration=3661)], settings=_settings())
    # 3661 seconds = 01:01:01
    assert "01:01:01" in xml_str


def test_empty_feed_is_valid() -> None:
    xml_str = build_feed([], settings=_settings())
    root = ET.fromstring(xml_str)
    items = root.findall(".//item")
    assert len(items) == 0
