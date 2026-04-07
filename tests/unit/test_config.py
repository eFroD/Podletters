"""Tests for podletters.config."""

from __future__ import annotations

import pytest

from podletters.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    get_settings.cache_clear()


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")


def test_loads_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("SENDER_WHITELIST", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.imap_host == "imap.example.com"
    assert settings.imap_port == 993
    assert settings.imap_user == "user@example.com"
    assert settings.sender_whitelist == []
    assert settings.target_lufs == -16.0
    assert settings.mp3_bitrate == "128k"


def test_sender_whitelist_split(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("SENDER_WHITELIST", "a@x.com, b@y.com ,c@z.com")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.sender_whitelist == ["a@x.com", "b@y.com", "c@z.com"]


def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(Exception):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    a = get_settings()
    b = get_settings()
    assert a is b
