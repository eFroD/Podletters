"""Tests for podletters.tts.f5tts_renderer (mocked, no GPU required)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from podletters.models import TranscriptSegment
from podletters.tts.f5tts_renderer import AudioChunk, F5TTSRenderer


@pytest.fixture()
def _mock_settings(monkeypatch: pytest.MonkeyPatch):
    settings = SimpleNamespace(
        f5tts_ref_audio_host1=Path("refs/host1.wav"),
        f5tts_ref_text_host1="Hallo.",
        f5tts_ref_audio_host2=Path("refs/host2.wav"),
        f5tts_ref_text_host2="Hi.",
    )
    with patch("podletters.tts.f5tts_renderer.get_settings", return_value=settings):
        yield settings


@pytest.fixture()
def fake_model():
    model = MagicMock()
    model.infer.return_value = (np.zeros(16000, dtype=np.float32), 16000, None)
    return model


def test_render_segment_returns_audio_chunk(_mock_settings, fake_model) -> None:
    renderer = F5TTSRenderer()
    renderer._model = fake_model

    seg = TranscriptSegment(speaker="HOST1", text="Hallo zusammen.")
    chunk = renderer.render_segment(seg)

    assert isinstance(chunk, AudioChunk)
    assert chunk.speaker == "HOST1"
    assert chunk.sample_rate == 16000
    assert len(chunk.audio) == 16000
    fake_model.infer.assert_called_once()


def test_render_segment_squeezes_2d(_mock_settings, fake_model) -> None:
    fake_model.infer.return_value = (np.zeros((1, 8000), dtype=np.float32), 16000, None)
    renderer = F5TTSRenderer()
    renderer._model = fake_model

    chunk = renderer.render_segment(TranscriptSegment(speaker="HOST2", text="Test."))
    assert chunk.audio.ndim == 1
    assert len(chunk.audio) == 8000


def test_render_segments_unloads_model(_mock_settings, fake_model) -> None:
    renderer = F5TTSRenderer()
    renderer._model = fake_model

    segments = [
        TranscriptSegment(speaker="HOST1", text="A."),
        TranscriptSegment(speaker="HOST2", text="B."),
    ]
    chunks = renderer.render_segments(segments)

    assert len(chunks) == 2
    assert renderer._model is None  # unloaded


def test_render_segments_skips_failed(_mock_settings, fake_model) -> None:
    call_count = 0

    def flaky_infer(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("GPU error")
        return (np.zeros(100, dtype=np.float32), 16000, None)

    fake_model.infer.side_effect = flaky_infer
    renderer = F5TTSRenderer()
    renderer._model = fake_model

    segments = [
        TranscriptSegment(speaker="HOST1", text="Fail."),
        TranscriptSegment(speaker="HOST2", text="OK."),
    ]
    chunks = renderer.render_segments(segments)
    assert len(chunks) == 1
    assert chunks[0].speaker == "HOST2"


def test_render_segments_all_fail_raises(_mock_settings, fake_model) -> None:
    fake_model.infer.side_effect = RuntimeError("boom")
    renderer = F5TTSRenderer()
    renderer._model = fake_model

    segments = [TranscriptSegment(speaker="HOST1", text="X.")]
    with pytest.raises(RuntimeError, match="All TTS segments failed"):
        renderer.render_segments(segments)


def test_unknown_speaker_raises(_mock_settings, fake_model) -> None:
    renderer = F5TTSRenderer()
    renderer._model = fake_model

    seg = TranscriptSegment.__new__(TranscriptSegment)
    object.__setattr__(seg, "speaker", "HOST3")
    object.__setattr__(seg, "text", "X.")

    with pytest.raises(ValueError, match="No voice profile"):
        renderer.render_segment(seg)


def test_context_manager_unloads(_mock_settings, fake_model) -> None:
    with F5TTSRenderer() as renderer:
        renderer._model = fake_model
    assert renderer._model is None
