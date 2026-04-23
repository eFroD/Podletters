"""Loudness normalization, true-peak limiting and MP3 encoding.

Implements FR-04.1 (−16 LUFS), FR-04.2 (128 kbps MP3) and FR-04.3
(ID3 metadata embedding).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pydub import AudioSegment

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


def _embed_cover_art(mp3_path: Path, cover_path: Path | None = None) -> None:
    """Embed cover art into the MP3's ID3 tags if the cover file exists."""
    if cover_path is None:
        cover_path = Path("refs/cover.png")
    if not cover_path.exists():
        return
    try:
        from mutagen.id3 import APIC
        from mutagen.mp3 import MP3

        audio = MP3(str(mp3_path))
        if audio.tags is None:
            audio.add_tags()
        mime = "image/png" if cover_path.suffix == ".png" else "image/jpeg"
        audio.tags.add(
            APIC(
                encoding=3,  # UTF-8
                mime=mime,
                type=3,  # Cover (front)
                desc="Cover",
                data=cover_path.read_bytes(),
            )
        )
        audio.save()
        logger.info("Embedded cover art from %s", cover_path)
    except ImportError:
        logger.debug("mutagen not installed; skipping cover art embedding")
    except Exception as exc:
        logger.warning("Failed to embed cover art: %s", exc)


def encode_mp3(
    audio: np.ndarray,
    sample_rate: int,
    output_path: Path,
    *,
    bitrate: str = "128k",
    title: str = "",
    artist: str = "",
    date: str = "",
    cover_path: Path | None = None,
) -> Path:
    """Encode a float32 numpy waveform to MP3 with ID3 tags and optional cover art.

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

    _embed_cover_art(output_path, cover_path)

    size_mb = output_path.stat().st_size / 1e6
    logger.info("Encoded MP3: %s (%.2f MB, %s)", output_path, size_mb, bitrate)
    return output_path


def compress_dynamic_range(
    audio: np.ndarray,
    sample_rate: int,
    *,
    threshold_db: float = -20.0,
    ratio: float = 3.0,
    attack_ms: float = 5.0,
    release_ms: float = 50.0,
) -> np.ndarray:
    """Apply simple feed-forward dynamic range compression.

    Reduces volume jumps between the two speakers (PRD §5.4). Parameters
    are intentionally conservative for speech — a 3:1 ratio above −20 dB
    smooths loud peaks without audible pumping.

    Toggled via ``ENABLE_COMPRESSION`` in Settings (default: True).
    """
    if len(audio) == 0:
        return audio

    threshold_lin = 10 ** (threshold_db / 20)
    attack_coeff = np.exp(-1.0 / (attack_ms * sample_rate / 1000))
    release_coeff = np.exp(-1.0 / (release_ms * sample_rate / 1000))

    envelope = np.zeros_like(audio)
    env = 0.0
    for i in range(len(audio)):
        level = abs(audio[i])
        if level > env:
            env = attack_coeff * env + (1 - attack_coeff) * level
        else:
            env = release_coeff * env + (1 - release_coeff) * level
        envelope[i] = env

    gain = np.ones_like(audio)
    above = envelope > threshold_lin
    if np.any(above):
        db_over = 20 * np.log10(np.clip(envelope[above] / threshold_lin, 1e-10, None))
        gain_reduction_db = db_over * (1 - 1 / ratio)
        gain[above] = 10 ** (-gain_reduction_db / 20)

    compressed = audio * gain
    logger.info(
        "Dynamic range compression: threshold=%.0f dB, ratio=%.1f:1",
        threshold_db,
        ratio,
    )
    return compressed


def postprocess(
    audio: np.ndarray,
    sample_rate: int,
    output_path: Path,
    *,
    title: str = "",
    artist: str = "",
    date: str = "",
    enable_compression: bool = True,
    settings: Settings | None = None,
) -> Path:
    """Full post-processing pipeline: normalize → compress → limit → encode.

    Returns the path to the final MP3 file.
    """
    settings = settings or get_settings()

    audio = normalize_loudness(audio, sample_rate, settings.target_lufs)
    if enable_compression:
        audio = compress_dynamic_range(audio, sample_rate)
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


__all__ = ["compress_dynamic_range", "encode_mp3", "normalize_loudness", "postprocess"]
