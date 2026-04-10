#!/usr/bin/env python3
"""End-to-end manual MVP pipeline.

Wires all Phase 1 components sequentially without Celery:

    IMAP fetch → text clean → Ollama transcript → F5-TTS render → merge → normalize → MP3

Usage::

    # Process the first unread newsletter from IMAP:
    python scripts/run_pipeline.py

    # Process a saved newsletter text file:
    python scripts/run_pipeline.py --file path/to/newsletter.txt

    # Use a pre-generated transcript JSON (skip LLM):
    python scripts/run_pipeline.py --transcript path/to/transcript.json

Output is written to ``out/episode_YYYYMMDD_<slug>.mp3``.

Phase 1 DoD: a listenable MP3 episode generated from a real newsletter.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Pipeline imports ──────────────────────────────────────────────────

from podletters.ingestion.imap_client import fetch_new_emails
from podletters.ingestion.text_cleaner import to_payload
from podletters.llm.ollama_client import OllamaClient
from podletters.llm.parser import TranscriptParseError, parse_llm_output
from podletters.llm.prompt import build_messages
from podletters.models import NewsletterPayload, TranscriptPayload
from podletters.postprocessing.normalize import postprocess
from podletters.tts.audio_merger import merge_chunks
from podletters.tts.f5tts_renderer import F5TTSRenderer

OUT_DIR = Path("out")

logger = logging.getLogger("podletters.pipeline")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:40] or "episode"


# ── Step functions ────────────────────────────────────────────────────


def step_ingest() -> NewsletterPayload:
    """Fetch the first unseen newsletter from IMAP and clean it."""
    logger.info("STEP 1/5 — Fetching newsletters from IMAP …")
    emails = fetch_new_emails()
    if not emails:
        raise SystemExit("No matching newsletters found in inbox.")
    email = emails[0]
    payload = to_payload(email)
    logger.info("  Newsletter: [%s] %s (%d chars)", payload.sender, payload.subject, len(payload.body_text))
    return payload


def step_ingest_from_file(path: Path) -> NewsletterPayload:
    """Build a payload from a local text file."""
    logger.info("STEP 1/5 — Loading newsletter from file: %s", path)
    body = path.read_text(encoding="utf-8")
    return NewsletterPayload(
        message_id=f"<file-{path.name}@localhost>",
        sender="file@localhost",
        sender_name=path.stem,
        subject=path.stem,
        received_at=datetime.now(timezone.utc),
        body_text=body,
    )


def step_generate_transcript(payload: NewsletterPayload) -> TranscriptPayload:
    """Send the newsletter body through Ollama and parse the result."""
    logger.info("STEP 2/5 — Generating transcript via Ollama …")
    messages = build_messages(payload)
    client = OllamaClient()
    t0 = time.monotonic()
    response = client.chat(messages)
    elapsed = time.monotonic() - t0
    logger.info("  Ollama returned %d chars in %.1fs", len(response.content), elapsed)
    transcript = parse_llm_output(response.content)
    logger.info("  Title: %s  (%d segments)", transcript.episode_title, len(transcript.segments))
    return transcript


def step_render_audio(transcript: TranscriptPayload):
    """Render all transcript segments via F5-TTS and merge."""
    logger.info("STEP 3/5 — Rendering audio via F5-TTS …")
    renderer = F5TTSRenderer()
    chunks = renderer.render_segments(transcript.segments)
    logger.info("  Rendered %d chunks", len(chunks))

    logger.info("STEP 4/5 — Merging audio …")
    merged, sr = merge_chunks(chunks)
    duration = len(merged) / sr
    logger.info("  Merged: %.1fs at %d Hz", duration, sr)
    return merged, sr


def step_postprocess(audio, sr, transcript: TranscriptPayload) -> Path:
    """Normalize loudness and encode to MP3."""
    logger.info("STEP 5/5 — Post-processing and MP3 encoding …")
    date_str = datetime.now().strftime("%Y%m%d")
    slug = _slugify(transcript.episode_title)
    filename = f"episode_{date_str}_{slug}.mp3"
    out_path = OUT_DIR / filename

    postprocess(
        audio,
        sr,
        out_path,
        title=transcript.episode_title,
        date=date_str,
    )
    size_mb = out_path.stat().st_size / 1e6
    logger.info("  Output: %s (%.2f MB)", out_path, size_mb)
    return out_path


# ── Main ──────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Podletters end-to-end MVP pipeline")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file", type=Path, help="Path to a plain-text newsletter file")
    group.add_argument("--transcript", type=Path, help="Path to a pre-generated transcript JSON (skips LLM)")
    args = parser.parse_args()

    t_start = time.monotonic()

    try:
        # -- Transcript phase --
        if args.transcript:
            logger.info("STEP 1/5 — Loading pre-generated transcript: %s", args.transcript)
            data = json.loads(args.transcript.read_text(encoding="utf-8"))
            transcript = TranscriptPayload(**data)
            logger.info("  Title: %s (%d segments)", transcript.episode_title, len(transcript.segments))
        else:
            if args.file:
                payload = step_ingest_from_file(args.file)
            else:
                payload = step_ingest()
            transcript = step_generate_transcript(payload)

        # -- Audio phase --
        merged, sr = step_render_audio(transcript)
        out_path = step_postprocess(merged, sr, transcript)

    except TranscriptParseError as exc:
        logger.error("LLM output could not be parsed: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 2

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 60}")
    print(f"  Episode ready: {out_path.resolve()}")
    print(f"  Title:         {transcript.episode_title}")
    print(f"  Segments:      {len(transcript.segments)}")
    print(f"  Total time:    {elapsed:.0f}s")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
