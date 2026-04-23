"""Tests for podletters.tts.audio_merger."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from podletters.tts.audio_merger import merge_chunks
from podletters.tts.f5tts_renderer import AudioChunk


def _settings(sr: int = 16000, silence_ms: int = 400):
    return SimpleNamespace(audio_sample_rate=sr, segment_silence_ms=silence_ms)


def _chunk(samples: int = 16000, sr: int = 16000, speaker: str = "HOST1") -> AudioChunk:
    return AudioChunk(
        audio=np.ones(samples, dtype=np.float32),
        sample_rate=sr,
        speaker=speaker,
    )


def test_single_chunk_no_silence() -> None:
    merged, sr = merge_chunks([_chunk(1000)], settings=_settings(16000, 400))
    assert sr == 16000
    assert len(merged) == 1000  # no trailing silence


def test_two_chunks_with_silence() -> None:
    s = _settings(16000, 500)  # 500 ms → 8000 samples
    merged, sr = merge_chunks([_chunk(1000), _chunk(2000)], settings=s)
    assert sr == 16000
    assert len(merged) == 1000 + 8000 + 2000


def test_silence_zero_ms() -> None:
    s = _settings(16000, 0)
    merged, _ = merge_chunks([_chunk(100), _chunk(200)], settings=s)
    assert len(merged) == 300


def test_resamples_different_rates() -> None:
    s = _settings(22050, 0)
    chunk = _chunk(16000, sr=16000)  # 1 second at 16kHz
    merged, sr = merge_chunks([chunk], settings=s)
    assert sr == 22050
    assert abs(len(merged) - 22050) < 2  # ~1 second worth of samples


def test_empty_list_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        merge_chunks([], settings=_settings())


def test_output_is_float32() -> None:
    merged, _ = merge_chunks([_chunk(100)], settings=_settings())
    assert merged.dtype == np.float32
