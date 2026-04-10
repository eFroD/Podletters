"""Render transcript segments to audio via F5-TTS.

Wraps ``f5_tts`` zero-shot voice cloning. The model is loaded once per
episode run and unloaded afterwards to free VRAM for the next pipeline
stage (PRD §5.3, FR-03.1, FR-03.2).

The public interface is :func:`render_segments` which takes a list of
:class:`~podletters.models.TranscriptSegment` and returns a list of
``(numpy_array, sample_rate)`` tuples — one per segment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from podletters.config import Settings, get_settings
from podletters.models import TranscriptSegment

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Reference audio + text for one speaker."""

    ref_audio_path: Path
    ref_text: str


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A rendered audio segment with its sample rate."""

    audio: np.ndarray
    sample_rate: int
    speaker: str


def _load_voice_profiles(settings: Settings) -> dict[str, VoiceProfile]:
    return {
        "HOST1": VoiceProfile(
            ref_audio_path=Path(settings.f5tts_ref_audio_host1),
            ref_text=settings.f5tts_ref_text_host1,
        ),
        "HOST2": VoiceProfile(
            ref_audio_path=Path(settings.f5tts_ref_audio_host2),
            ref_text=settings.f5tts_ref_text_host2,
        ),
    }


class F5TTSRenderer:
    """Manages F5-TTS model lifecycle and renders text segments to audio."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._voices = _load_voice_profiles(self._settings)
        self._model = None

    def _ensure_model(self) -> None:
        """Lazy-load the F5-TTS model into VRAM."""
        if self._model is not None:
            return
        try:
            from f5_tts.api import F5TTS

            logger.info("Loading F5-TTS model into VRAM …")
            self._model = F5TTS()
            logger.info("F5-TTS model loaded")
        except Exception:
            logger.exception("Failed to load F5-TTS model")
            raise

    def unload(self) -> None:
        """Release the model and free VRAM."""
        if self._model is not None:
            del self._model
            self._model = None
            # Best-effort CUDA cache clear.
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            logger.info("F5-TTS model unloaded")

    def render_segment(self, segment: TranscriptSegment) -> AudioChunk:
        """Render a single transcript segment using the speaker's voice profile.

        Returns an :class:`AudioChunk` with the rendered numpy waveform.
        """
        self._ensure_model()
        voice = self._voices.get(segment.speaker)
        if voice is None:
            raise ValueError(f"No voice profile for speaker {segment.speaker!r}")

        ref_audio = str(voice.ref_audio_path)
        logger.debug(
            "Rendering segment: speaker=%s, chars=%d",
            segment.speaker,
            len(segment.text),
        )

        audio, sample_rate, _ = self._model.infer(  # type: ignore[union-attr]
            ref_file=ref_audio,
            ref_text=voice.ref_text,
            gen_text=segment.text,
        )
        # F5-TTS returns (wav_np, sr, spectrogram). wav_np may be 2-D (1, N).
        if audio.ndim > 1:
            audio = audio.squeeze()

        return AudioChunk(audio=audio, sample_rate=sample_rate, speaker=segment.speaker)

    def render_segments(
        self, segments: list[TranscriptSegment]
    ) -> list[AudioChunk]:
        """Render all segments sequentially (FR-03.2). Unloads model after."""
        logger.info("Rendering %d segments via F5-TTS", len(segments))
        chunks: list[AudioChunk] = []
        try:
            for i, seg in enumerate(segments, 1):
                try:
                    chunk = self.render_segment(seg)
                    chunks.append(chunk)
                    logger.info(
                        "  [%d/%d] %s — %d samples",
                        i,
                        len(segments),
                        seg.speaker,
                        len(chunk.audio),
                    )
                except Exception:
                    # FR-03: skip failed segments, continue with rest.
                    logger.exception(
                        "  [%d/%d] %s — FAILED, skipping", i, len(segments), seg.speaker
                    )
        finally:
            self.unload()

        if not chunks:
            raise RuntimeError("All TTS segments failed; no audio produced")
        return chunks

    def __enter__(self) -> "F5TTSRenderer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.unload()


__all__ = ["AudioChunk", "F5TTSRenderer", "VoiceProfile"]
