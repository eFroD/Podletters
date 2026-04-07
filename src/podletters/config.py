"""Application settings loaded from environment / .env file.

All variables defined in PRD §15 are mapped here. Use ``get_settings()``
to access a cached singleton instance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed configuration for the Podletters pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Email / IMAP ----
    imap_host: str = Field(..., description="IMAP server hostname")
    imap_port: int = Field(993, ge=1, le=65535)
    imap_user: str
    imap_password: str
    imap_folder: str = "INBOX"
    sender_whitelist: list[str] = Field(
        default_factory=list,
        description="Comma-separated list of sender addresses to accept",
    )
    poll_interval_seconds: int = Field(900, ge=30)

    # ---- LLM / Ollama ----
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:32b-instruct-q4_K_M"
    ollama_timeout_seconds: int = Field(300, ge=10)

    # ---- TTS / F5-TTS ----
    f5tts_ref_audio_host1: Path = Path("refs/host1.wav")
    f5tts_ref_text_host1: str = "Hallo und willkommen, schön dass du dabei bist."
    f5tts_ref_audio_host2: Path = Path("refs/host2.wav")
    f5tts_ref_text_host2: str = "Genau, das finde ich wirklich interessant."
    segment_silence_ms: int = Field(400, ge=0, le=5000)

    # ---- Audio post-processing ----
    target_lufs: float = -16.0
    mp3_bitrate: str = "128k"
    audio_sample_rate: int = Field(22050, ge=8000, le=48000)

    # ---- Storage / MinIO ----
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "podcast-episodes"

    # ---- Celery / Redis ----
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ---- Podcast metadata ----
    podcast_title: str = "Mein Newsletter Podcast"
    podcast_author: str = "Eric"
    podcast_base_url: str = "http://localhost:9000"

    @field_validator("sender_whitelist", mode="before")
    @classmethod
    def _split_whitelist(cls, value: object) -> object:
        """Allow ``SENDER_WHITELIST`` to be a comma-separated string in .env."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()  # type: ignore[call-arg]
