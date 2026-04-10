"""Concatenate rendered audio chunks with silence padding.

Implements FR-03.3 (configurable silence gap) and FR-03.4 (single
continuous waveform). Handles resampling when chunks have different
sample rates by resampling all to the target ``AUDIO_SAMPLE_RATE``.
"""

from __future__ import annotations

import logging

import numpy as np

from podletters.config import Settings, get_settings
from podletters.tts.f5tts_renderer import AudioChunk

logger = logging.getLogger(__name__)


def _resample(audio: np.ndarray, src_sr: int, target_sr: int) -> np.ndarray:
    """Naive linear resampling. Good enough for speech; avoids a scipy dep."""
    if src_sr == target_sr:
        return audio
    ratio = target_sr / src_sr
    new_length = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, new_length)
    return np.interp(indices, np.arange(len(audio)), audio).astype(audio.dtype)


def merge_chunks(
    chunks: list[AudioChunk],
    settings: Settings | None = None,
) -> tuple[np.ndarray, int]:
    """Merge audio chunks into a single waveform with silence gaps.

    Parameters
    ----------
    chunks:
        Ordered list of rendered :class:`AudioChunk` objects.
    settings:
        Pipeline settings (used for ``segment_silence_ms`` and
        ``audio_sample_rate``). Falls back to ``get_settings()``.

    Returns
    -------
    tuple[np.ndarray, int]
        ``(waveform, sample_rate)`` — a single mono float32 array.
    """
    if not chunks:
        raise ValueError("Cannot merge an empty chunk list")

    settings = settings or get_settings()
    target_sr = settings.audio_sample_rate
    silence_ms = settings.segment_silence_ms
    silence_samples = int(target_sr * silence_ms / 1000)
    silence = np.zeros(silence_samples, dtype=np.float32)

    parts: list[np.ndarray] = []
    for i, chunk in enumerate(chunks):
        audio = _resample(chunk.audio, chunk.sample_rate, target_sr)
        parts.append(audio.astype(np.float32))
        # Insert silence between segments, but not after the last one.
        if i < len(chunks) - 1:
            parts.append(silence)

    merged = np.concatenate(parts)
    total_seconds = len(merged) / target_sr
    logger.info(
        "Merged %d chunks → %.1fs at %d Hz (%d silence-gap ms)",
        len(chunks),
        total_seconds,
        target_sr,
        silence_ms,
    )
    return merged, target_sr


__all__ = ["merge_chunks"]
