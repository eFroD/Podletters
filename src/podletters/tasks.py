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

import logging
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from celery import chain

from podletters.celery_app import app

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "episode"


# ──────────────────────────────────────────────────────────────────────
# Task 22: ingest_email_task
# ──────────────────────────────────────────────────────────────────────


@app.task(
    name="podletters.ingest_email",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
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


@app.task(
    name="podletters.generate_transcript",
    bind=True,
    autoretry_for=(ConnectionError, OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
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


@app.task(
    name="podletters.render_audio",
    bind=True,
    autoretry_for=(RuntimeError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def render_audio(self, prev_result: dict) -> dict:
    """Render transcript segments via F5-TTS and merge into a single waveform."""
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


@app.task(
    name="podletters.postprocess_audio",
    bind=True,
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=3,
)
def postprocess_audio(self, prev_result: dict) -> dict:
    """Normalize loudness and encode to MP3."""
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
# Task 29: upload_episode_task
# ──────────────────────────────────────────────────────────────────────


@app.task(
    name="podletters.upload_episode",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    max_retries=3,
)
def upload_episode(self, prev_result: dict) -> dict:
    """Upload MP3 + metadata JSON to MinIO and clean up the temp file."""
    from podletters.models import EpisodeMetadata, TranscriptPayload
    from podletters.storage.episode_counter import EpisodeCounter
    from podletters.storage.minio_client import MinIOClient

    transcript = TranscriptPayload(**prev_result["transcript"])
    mp3_path = Path(prev_result["mp3_path"])
    date_str = prev_result["date_str"]
    slug = prev_result["slug"]

    episode_number = EpisodeCounter().next()
    minio = MinIOClient()
    episode_id = f"{date_str}-{slug}"
    mp3_key = f"{date_str[:4]}/{date_str[4:6]}/{mp3_path.name}"
    file_url = minio.get_public_url(mp3_key)

    metadata = EpisodeMetadata(
        episode_id=episode_id,
        episode_number=episode_number,
        title=transcript.episode_title,
        description=transcript.episode_description,
        source_sender=prev_result["payload"].get("sender", ""),
        duration_seconds=prev_result["duration_seconds"],
        file_size_bytes=prev_result["file_size_bytes"],
        file_url=file_url,
        created_at=datetime.now(timezone.utc),
        transcript_segments=len(transcript.segments),
    )

    mp3_key = minio.upload_episode(mp3_path, metadata)
    logger.info("[upload] Uploaded to MinIO: %s", mp3_key)

    # Clean up temp MP3.
    mp3_path.unlink(missing_ok=True)

    return {
        "episode_id": episode_id,
        "title": transcript.episode_title,
        "mp3_key": mp3_key,
        "file_url": file_url,
    }


# ──────────────────────────────────────────────────────────────────────
# Task 44: retention / cleanup task
# ──────────────────────────────────────────────────────────────────────


@app.task(name="podletters.cleanup_old_episodes", bind=True)
def cleanup_old_episodes(self, max_age_days: int = 0) -> dict:
    """Delete episodes older than ``max_age_days`` from MinIO.

    If ``max_age_days`` is 0 (default) or negative, the task is a no-op.
    This keeps the PRD's "no automatic deletion" default while allowing
    opt-in retention management via Celery Beat or a manual call::

        cleanup_old_episodes.delay(max_age_days=90)
    """
    if max_age_days <= 0:
        logger.info("[cleanup] Retention disabled (max_age_days=%d)", max_age_days)
        return {"deleted": 0, "skipped": "retention disabled"}

    from podletters.storage.minio_client import MinIOClient

    minio = MinIOClient()
    episodes = minio.list_episode_metadata()
    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=max_age_days)
    deleted = 0

    for ep in episodes:
        created = ep.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            try:
                minio.delete_episode(ep)
                deleted += 1
                logger.info("[cleanup] Deleted: %s (%s)", ep.episode_id, ep.title)
            except Exception:
                logger.exception("[cleanup] Failed to delete %s", ep.episode_id)

    logger.info("[cleanup] Retention pass complete: deleted=%d", deleted)
    return {"deleted": deleted, "max_age_days": max_age_days}
