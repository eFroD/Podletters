"""Integration test for the Podletters pipeline.

Requires a running Compose stack (redis, minio, ollama, worker). Run with::

    make up
    PYTHONPATH=src pytest tests/integration/ -v --timeout=300

This test:
1. Pushes a ``NewsletterPayload`` dict directly into the task chain
   (bypasses IMAP).
2. Waits for the chain to complete.
3. Asserts that an MP3 + JSON metadata pair appeared in MinIO.

Marked with ``@pytest.mark.integration`` so unit test runs can skip it.
"""

from __future__ import annotations

import json
import time

import pytest

INTEGRATION = pytest.mark.integration


@INTEGRATION
def test_pipeline_chain_produces_episode_in_minio():
    """Full chain: generate_transcript → render_audio → postprocess → upload."""
    from datetime import datetime, timezone

    from podletters.models import NewsletterPayload
    from podletters.storage.minio_client import MinIOClient
    from podletters.tasks import (
        generate_transcript,
        postprocess_audio,
        render_audio,
        upload_episode,
    )

    # ── Arrange ──────────────────────────────────────────────────────
    payload = NewsletterPayload(
        message_id="<integration-test@localhost>",
        sender="test@localhost",
        sender_name="Integration Test",
        subject="Integration Test Newsletter",
        received_at=datetime.now(timezone.utc),
        body_text=(
            "Today OpenAI released GPT-5. The model is 3x faster. "
            "Meanwhile, Google announced Gemini 3 with 2M context. "
            "Meta open-sourced Llama 4 under an open license."
        ),
    )
    payload_dict = payload.model_dump(mode="json")

    # ── Act ──────────────────────────────────────────────────────────
    # Run the chain synchronously (apply, not apply_async) so we can
    # wait on the result without needing a running worker process.
    from celery import chain

    pipeline = chain(
        generate_transcript.s(payload_dict),
        render_audio.s(),
        postprocess_audio.s(),
        upload_episode.s(),
    )
    result = pipeline.apply()  # synchronous, in-process execution
    final = result.get(timeout=600)

    # ── Assert ───────────────────────────────────────────────────────
    assert "episode_id" in final
    assert "mp3_key" in final
    assert final["mp3_key"].endswith(".mp3")

    # Verify files exist in MinIO.
    minio = MinIOClient()
    episodes = minio.list_episode_metadata()
    matching = [e for e in episodes if e.episode_id == final["episode_id"]]
    assert len(matching) == 1, f"Expected 1 episode, found {len(matching)}"

    meta = matching[0]
    assert meta.duration_seconds > 0
    assert meta.file_size_bytes > 0
    assert meta.transcript_segments > 0
    assert "Integration" in meta.title or meta.source_sender == "test@localhost"


@INTEGRATION
def test_ingest_email_with_empty_inbox():
    """ingest_email returns gracefully when no mail is fetched."""
    from unittest.mock import patch

    from podletters.tasks import ingest_email

    with patch("podletters.tasks.fetch_new_emails", return_value=[]):
        result = ingest_email.apply().get(timeout=10)

    assert result == {"ingested": 0}
