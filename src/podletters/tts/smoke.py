"""Manual smoke test for the TTS rendering stack.

Run as::

    python -m podletters.tts.smoke [path/to/transcript.json]

If no path is given, a small built-in sample transcript is used. The script
loads F5-TTS, renders all segments, merges them with silence padding, and
writes a raw WAV file to ``out/tts_smoke.wav``.

This is the **TTS quality decision point**: listen to the output and
decide whether F5-TTS German quality is sufficient or whether to switch
to XTTS-v2.

Exit codes:
    0  WAV written successfully
    2  fatal error (model load failure, CUDA OOM, …)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from podletters.models import TranscriptPayload
from podletters.tts.audio_merger import merge_chunks
from podletters.tts.f5tts_renderer import F5TTSRenderer

_SAMPLE_TRANSCRIPT = {
    "episode_title": "TTS Smoke Test",
    "episode_description": "Rauchtest für die Sprachsynthese.",
    "segments": [
        {"speaker": "HOST1", "text": "Hallo und willkommen zu unserem Podcast! Heute testen wir die Sprachsynthese."},
        {"speaker": "HOST2", "text": "Genau, das wird spannend! Ich bin schon sehr gespannt auf die Qualität."},
        {"speaker": "HOST1", "text": "Lass uns direkt loslegen. Das erste Thema ist künstliche Intelligenz."},
        {"speaker": "HOST2", "text": "Oh ja, da hat sich in letzter Zeit wirklich sehr viel getan!"},
    ],
}

OUT_DIR = Path("out")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
    )
    log = logging.getLogger("podletters.tts.smoke")

    # Load transcript.
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            log.error("File not found: %s", path)
            return 2
        data = json.loads(path.read_text(encoding="utf-8"))
        source = path.name
    else:
        data = _SAMPLE_TRANSCRIPT
        source = "built-in sample"

    transcript = TranscriptPayload(**data)
    log.info(
        "Transcript: %s (%d segments, source=%s)",
        transcript.episode_title,
        len(transcript.segments),
        source,
    )

    # Render.
    try:
        renderer = F5TTSRenderer()
        chunks = renderer.render_segments(transcript.segments)
    except Exception as exc:
        log.error("TTS rendering failed: %s", exc)
        return 2

    # Merge.
    merged, sr = merge_chunks(chunks)
    duration = len(merged) / sr
    log.info("Merged audio: %.1fs at %d Hz", duration, sr)

    # Write WAV.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = OUT_DIR / "tts_smoke.wav"
    sf.write(str(wav_path), merged, sr)
    log.info("Wrote %s (%.1f MB)", wav_path, wav_path.stat().st_size / 1e6)

    print(f"\nListening checkpoint: {wav_path.resolve()}")
    print("If German quality is acceptable → continue with Phase 1.")
    print("If not → evaluate XTTS-v2 as fallback.")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual tool
    sys.exit(main())
