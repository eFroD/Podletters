"""Tests for podletters.models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from podletters.models import (
    EpisodeMetadata,
    NewsletterPayload,
    TranscriptPayload,
    TranscriptSegment,
)


def test_newsletter_payload_roundtrip() -> None:
    payload = NewsletterPayload(
        message_id="abc123@example.com",
        sender="tldrnewsletter@example.com",
        sender_name="TLDR",
        subject="TLDR 2026-04-07",
        received_at=datetime(2026, 4, 7, 8, 0, tzinfo=timezone.utc),
        body_text="Hello world",
    )
    assert payload.body_text == "Hello world"
    # frozen
    with pytest.raises(ValidationError):
        payload.body_text = "changed"  # type: ignore[misc]


def test_newsletter_payload_requires_body() -> None:
    with pytest.raises(ValidationError):
        NewsletterPayload(
            message_id="x",
            sender="a@b.c",
            sender_name="",
            subject="s",
            received_at=datetime.now(timezone.utc),
            body_text="",
        )


def test_transcript_segment_speaker_enum() -> None:
    TranscriptSegment(speaker="HOST1", text="Hallo")
    TranscriptSegment(speaker="HOST2", text="Hi")
    with pytest.raises(ValidationError):
        TranscriptSegment(speaker="HOST3", text="x")  # type: ignore[arg-type]


def test_transcript_payload_requires_segments() -> None:
    with pytest.raises(ValidationError):
        TranscriptPayload(
            episode_title="t",
            episode_description="d",
            segments=[],
        )


def test_episode_metadata_validation() -> None:
    meta = EpisodeMetadata(
        episode_id="20260407-tldr",
        title="TLDR – 7. April 2026",
        description="…",
        source_sender="tldrnewsletter@example.com",
        duration_seconds=480,
        file_size_bytes=7_680_000,
        file_url="http://localhost:9000/podcast-episodes/2026/04/episode_20260407_tldr.mp3",
        created_at=datetime(2026, 4, 7, 9, 15, tzinfo=timezone.utc),
        transcript_segments=24,
    )
    assert meta.duration_seconds == 480
    with pytest.raises(ValidationError):
        EpisodeMetadata(
            episode_id="x",
            title="t",
            description="d",
            source_sender="a@b.c",
            duration_seconds=-1,
            file_size_bytes=0,
            file_url="http://localhost:9000/x.mp3",
            created_at=datetime.now(timezone.utc),
            transcript_segments=0,
        )
