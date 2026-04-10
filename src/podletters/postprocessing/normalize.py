"""Loudness normalization, true-peak limiting and MP3 encoding.

Implements FR-04.1 (−16 LUFS), FR-04.2 (128 kbps MP3) and FR-04.3
(ID3 metadata embedding).
"""

from __future__ import annotations

import io
import logging
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pydub import AudioSegment
from pydub.utils import mediainfo

from podletters.config import Settings, get_settings

logger = logging.getLogger(__name__)


def normalize_loudness(
    audio: np.ndarray,
    sample_rate: int,
    target_lufs: float = -16.0,
) -> np.ndarray:
    """Normalize integrated loudness to ``target_lufs``.

    Applies a simple gain adjustment via ``pyloudnorm``. If the input is
    silent (−inf LUFS), the audio is returned unchanged with a warning.
    """
    meter = pyln.Meter(sample_rate)
    current_lufs = meter.integrated_loudness(audio)

    if not np.isfinite(current_lufs):
        logger.warning("Input is silent (−inf LUFS); skipping normalization")
        return audio

    normalized = pyln.normalize.loudness(audio, current_lufs, target_lufs)
    logger.info(
        "Loudness: %.1f LUFS → %.1f LUFS (gain %.1f dB)",
        current_lufs,
        target_lufs,
        target_lufs - current_lufs,
    )
    return normalized


def _true_peak_limit(audio: np.ndarray, ceiling_dbtp: float = -1.0) -> np.ndarray:
    """Clamp true peak to ``ceiling_dbtp``. Simple hard limiter."""
    peak = np.max(np.abs(audio))
    if peak == 0:
        return audio
    peak_db = 20 * np.log10(peak)
    if peak_db > ceiling_dbtp:
        reduction = 10 ** ((ceiling_dbtp - peak_db) / 20)
        audio = audio * reduction
        logger.info("True-peak limited: %.1f dBTP → %.1f dBTP", peak_db, ceiling_dbtp)
    return audio


def encode_mp3(
    audio: np.ndarray,
    sample_rate: int,
    output_path: Path,
    *,
    bitrate: str = "128k",
    title: str = "",
    artist: str = "",
    date: str = "",
) -> Path:
    """Encode a float32 numpy waveform to MP3 with ID3 tags.

    Uses a temporary WAV as an intermediate step because pydub (ffmpeg)
    works best with file inputs.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = Path(tmp.name)
    try:
        sf.write(str(tmp_wav), audio, sample_rate)
        segment = AudioSegment.from_wav(str(tmp_wav))
    finally:
        tmp_wav.unlink(missing_ok=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    tags: dict[str, str] = {}
    if title:
        tags["title"] = title
    if artist:
        tags["artist"] = artist
    if date:
        tags["date"] = date

    segment.export(
        str(output_path),
        format="mp3",
        bitrate=bitrate,
        tags=tags or None,
    )
    size_mb = output_path.stat().st_size / 1e6
    logger.info("Encoded MP3: %s (%.2f MB, %s)", output_path, size_mb, bitrate)
    return output_path


def postprocess(
    audio: np.ndarray,
    sample_rate: int,
    output_path: Path,
    *,
    title: str = "",
    artist: str = "",
    date: str = "",
    settings: Settings | None = None,
) -> Path:
    """Full post-processing pipeline: normalize → limit → encode.

    Returns the path to the final MP3 file.
    """
    settings = settings or get_settings()

    audio = normalize_loudness(audio, sample_rate, settings.target_lufs)
    audio = _true_peak_limit(audio, ceiling_dbtp=-1.0)
    return encode_mp3(
        audio,
        sample_rate,
        output_path,
        bitrate=settings.mp3_bitrate,
        title=title,
        artist=artist or settings.podcast_author,
        date=date,
    )


__all__ = ["encode_mp3", "normalize_loudness", "postprocess"]
