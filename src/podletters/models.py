"""Pydantic data models passed between pipeline stages.

These models are the canonical contracts for the Celery task graph and
mirror the schemas defined in PRD §5.1 (NewsletterPayload), §5.2
(TranscriptPayload) and §5.5 (EpisodeMetadata).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Speaker = Literal["HOST1", "HOST2"]


class NewsletterPayload(BaseModel):
    """Cleaned newsletter handed from ingestion to the LLM stage (PRD §5.1)."""

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(..., description="RFC 5322 Message-ID header")
    sender: str = Field(..., description="Envelope sender address")
    sender_name: str = Field("", description="Display name of the sender")
    subject: str = Field(..., description="Email subject")
    received_at: datetime = Field(..., description="When the message was received")
    body_text: str = Field(..., min_length=1, description="Cleaned plain-text body")


class TranscriptSegment(BaseModel):
    """A single dialogue turn produced by the LLM."""

    model_config = ConfigDict(frozen=True)

    speaker: Speaker
    text: str = Field(..., min_length=1)


class TranscriptPayload(BaseModel):
    """Structured podcast script returned by the LLM stage (PRD §5.2)."""

    episode_title: str = Field(..., max_length=120)
    episode_description: str = Field(..., min_length=1)
    segments: list[TranscriptSegment] = Field(..., min_length=1)


class EpisodeMetadata(BaseModel):
    """Metadata persisted alongside each MP3 in MinIO (PRD §5.5)."""

    episode_id: str = Field(..., description="Stable identifier, e.g. '20260407-tldr'")
    episode_number: int = Field(0, ge=0, description="Monotonic counter for itunes:episode")
    title: str
    description: str
    source_sender: str
    duration_seconds: int = Field(..., ge=0)
    file_size_bytes: int = Field(..., ge=0)
    file_url: HttpUrl
    created_at: datetime
    transcript_segments: int = Field(..., ge=0)
