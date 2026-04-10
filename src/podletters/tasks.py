"""Celery task definitions for the Podletters pipeline.

Task graph (PRD §5.7)::

    poll_emails
      └── ingest_email  (per newsletter)
            └── generate_transcript
                  └── render_audio
                        └── postprocess_audio
                              └── upload_episode
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from celery import chain

from podletters.celery_app import app
from podletters.config import get_settings

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "episode"


# ──────────────────────────────────────────────────────────────────────
# Task 22: ingest_email_task
# ──────────────────────────────────────────────────────────────────────

@app.task(name="podletters.ingest_email", bind=True)
def ingest_email(self):
    """Poll IMAP, filter, deduplicate, clean, and fan-out one chain per newsletter."""
    from podletters.ingestion.dedup import DedupStore
    from podletters.ingestion.imap_client import fetch_new_emails
    from podletters.ingestion.text_cleaner import to_payload

    logger.info("[ingest] Polling IMAP for new newsletters …")
    emails = fetch_new_emails()
    if not emails:
        logger.info("[ingest] No new newsletters")
        return {"ingested": 0}

    dedup = DedupStore.from_settings()
    dispatched = 0

    for email in emails:
        if dedup.is_processed(email.message_id):
            logger.debug("[ingest] Skipping duplicate: %s", email.message_id)
            continue

        try:
            payload = to_payload(email)
        except ValueError as exc:
            logger.warning("[ingest] Skipping %s: %s", email.message_id, exc)
            continue

        dedup.mark_processed(email.message_id)
        payload_dict = payload.model_dump(mode="json")

        # Kick off the downstream chain for this newsletter.
        pipeline = chain(
            generate_transcript.s(payload_dict),
            render_audio.s(),
            postprocess_audio.s(),
            upload_episode.s(),
        )
        pipeline.apply_async()
        dispatched += 1
        logger.info(
            "[ingest] Dispatched pipeline for [%s] %s",
            payload.sender,
            payload.subject,
        )

    return {"ingested": dispatched}


# ──────────────────────────────────────────────────────────────────────
# Task 23: generate_transcript_task
# ──────────────────────────────────────────────────────────────────────

@app.task(name="podletters.generate_transcript", bind=True)
def generate_transcript(self, payload_dict: dict) -> dict:
    """Send newsletter through Ollama and parse the transcript."""
    from podletters.llm.ollama_client import OllamaClient
    from podletters.llm.parser import parse_llm_output
    from podletters.llm.prompt import build_messages
    from podletters.models import NewsletterPayload

    payload = NewsletterPayload(**payload_dict)
    logger.info("[transcript] Generating for: %s", payload.subject)

    messages = build_messages(payload)
    client = OllamaClient()
    t0 = time.monotonic()
    response = client.chat(messages)
    elapsed = time.monotonic() - t0
    logger.info("[transcript] Ollama: %d chars in %.1fs", len(response.content), elapsed)

    transcript = parse_llm_output(response.content)
    logger.info(
        "[transcript] Parsed: %s (%d segments)",
        transcript.episode_title,
        len(transcript.segments),
    )

    return {
        "payload": payload_dict,
        "transcript": transcript.model_dump(mode="json"),
    }


# ──────────────────────────────────────────────────────────────────────
# Task 24: render_audio_task
# ──────────────────────────────────────────────────────────────────────

@app.task(name="podletters.render_audio", bind=True)
def render_audio(self, prev_result: dict) -> dict:
    """Render transcript segments via F5-TTS and merge into a single waveform."""
    import numpy as np
    import soundfile as sf

    from podletters.models import TranscriptPayload
    from podletters.tts.audio_merger import merge_chunks
    from podletters.tts.f5tts_renderer import F5TTSRenderer

    transcript = TranscriptPayload(**prev_result["transcript"])
    logger.info("[render] Rendering %d segments via F5-TTS", len(transcript.segments))

    renderer = F5TTSRenderer()
    chunks = renderer.render_segments(transcript.segments)
    merged, sr = merge_chunks(chunks)

    # Write raw WAV to a temp file so we can pass a path to the next task.
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir="/tmp")
    sf.write(tmp.name, merged, sr)
    tmp.close()
    duration_s = len(merged) / sr
    logger.info("[render] Merged: %.1fs → %s", duration_s, tmp.name)

    return {
        "payload": prev_result["payload"],
        "transcript": prev_result["transcript"],
        "wav_path": tmp.name,
        "sample_rate": sr,
        "duration_seconds": int(duration_s),
    }


# ──────────────────────────────────────────────────────────────────────
# Task 25: postprocess_audio_task
# ──────────────────────────────────────────────────────────────────────

@app.task(name="podletters.postprocess_audio", bind=True)
def postprocess_audio(self, prev_result: dict) -> dict:
    """Normalize loudness and encode to MP3."""
    import numpy as np
    import soundfile as sf

    from podletters.models import TranscriptPayload
    from podletters.postprocessing.normalize import postprocess

    transcript = TranscriptPayload(**prev_result["transcript"])
    wav_path = Path(prev_result["wav_path"])

    logger.info("[postprocess] Loading WAV: %s", wav_path)
    audio, sr = sf.read(str(wav_path), dtype="float32")
    wav_path.unlink(missing_ok=True)  # clean up temp

    date_str = datetime.now().strftime("%Y%m%d")
    slug = _slugify(transcript.episode_title)
    filename = f"episode_{date_str}_{slug}.mp3"
    mp3_path = Path(tempfile.gettempdir()) / filename

    postprocess(
        audio,
        sr,
        mp3_path,
        title=transcript.episode_title,
        date=date_str,
    )
    file_size = mp3_path.stat().st_size
    logger.info("[postprocess] MP3: %s (%.2f MB)", mp3_path, file_size / 1e6)

    return {
        "payload": prev_result["payload"],
        "transcript": prev_result["transcript"],
        "mp3_path": str(mp3_path),
        "mp3_filename": filename,
        "duration_seconds": prev_result["duration_seconds"],
        "file_size_bytes": file_size,
        "date_str": date_str,
        "slug": slug,
    }


# ──────────────────────────────────────────────────────────────────────
# Task 29 (placeholder): upload_episode_task
# Full MinIO integration comes in task 28/29 — this stub passes data
# through so the chain doesn't break during development.
# ──────────────────────────────────────────────────────────────────────

@app.task(name="podletters.upload_episode", bind=True)
def upload_episode(self, prev_result: dict) -> dict:
    """Upload MP3 + metadata to MinIO. (Stub — wired in task 29.)"""
    logger.info(
        "[upload] Episode ready: %s (%s, %d bytes)",
        prev_result.get("mp3_filename"),
        prev_result.get("slug"),
        prev_result.get("file_size_bytes", 0),
    )
    return prev_result
