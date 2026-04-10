"""Tests for podletters.postprocessing.normalize."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from podletters.postprocessing.normalize import (
    _true_peak_limit,
    normalize_loudness,
    postprocess,
)


def _tone(freq: float = 440.0, duration: float = 1.0, sr: int = 22050) -> np.ndarray:
    """Generate a sine tone for testing."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False, dtype=np.float32)
    return 0.5 * np.sin(2 * np.pi * freq * t)


def test_normalize_loudness_adjusts_level() -> None:
    tone = _tone()
    before_meter = __import__("pyloudnorm").Meter(22050)
    before_lufs = before_meter.integrated_loudness(tone)
    normalized = normalize_loudness(tone, 22050, target_lufs=-16.0)
    after_lufs = before_meter.integrated_loudness(normalized)
    assert abs(after_lufs - (-16.0)) < 0.5


def test_normalize_loudness_silent_input() -> None:
    silent = np.zeros(22050, dtype=np.float32)
    result = normalize_loudness(silent, 22050, target_lufs=-16.0)
    assert np.allclose(result, 0.0)


def test_true_peak_limit_reduces_peak() -> None:
    loud = np.array([2.0, -1.5, 0.5], dtype=np.float32)
    limited = _true_peak_limit(loud, ceiling_dbtp=-1.0)
    peak_db = 20 * np.log10(np.max(np.abs(limited)))
    assert peak_db <= -1.0 + 0.01


def test_true_peak_limit_noop_if_below() -> None:
    quiet = np.array([0.1, -0.1], dtype=np.float32)
    limited = _true_peak_limit(quiet, ceiling_dbtp=-1.0)
    np.testing.assert_array_equal(limited, quiet)


def test_postprocess_writes_mp3(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        target_lufs=-16.0,
        mp3_bitrate="128k",
        podcast_author="Test",
    )
    tone = _tone(duration=2.0)
    out = tmp_path / "test.mp3"
    with patch("podletters.postprocessing.normalize.get_settings", return_value=settings):
        result = postprocess(
            tone,
            22050,
            out,
            title="Episode 1",
            date="2026-04-07",
            settings=settings,
        )
    assert result.exists()
    assert result.suffix == ".mp3"
    assert result.stat().st_size > 0
