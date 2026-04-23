"""HTTP client for Ollama's ``/api/chat`` endpoint.

Thin wrapper around ``httpx`` that sends a system + user message pair and
returns the assistant reply. After each call the model is unloaded
(``keep_alive=0``) so that F5-TTS can claim the GPU (PRD §10 / NFR-04).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from podletters.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """Wrapper around the relevant fields of an Ollama /api/chat response."""

    content: str
    model: str
    total_duration_ns: int
    eval_count: int


class OllamaClient:
    """Synchronous Ollama chat client."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_model
        self._timeout = timeout or settings.ollama_timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "OllamaClient":
        settings = settings or get_settings()
        return cls(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
        )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        keep_alive: int | str = 0,
    ) -> ChatResponse:
        """Send a chat completion request. Returns the assistant reply.

        Parameters
        ----------
        messages:
            Ordered list of system/user/assistant messages.
        model:
            Override the default model for this single call.
        keep_alive:
            How long Ollama should keep the model resident after the call.
            Default ``0`` → unload immediately so TTS can reclaim VRAM.
        """
        model = model or self._model
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "keep_alive": keep_alive,
        }
        url = f"{self._base_url}/api/chat"
        logger.info("Ollama request: model=%s, messages=%d", model, len(messages))

        resp = httpx.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        body = resp.json()

        content = body.get("message", {}).get("content", "")
        result = ChatResponse(
            content=content,
            model=body.get("model", model),
            total_duration_ns=body.get("total_duration", 0),
            eval_count=body.get("eval_count", 0),
        )
        dur_s = result.total_duration_ns / 1e9
        logger.info(
            "Ollama response: %d chars, %d tokens, %.1fs",
            len(result.content),
            result.eval_count,
            dur_s,
        )
        return result


__all__ = ["ChatMessage", "ChatResponse", "OllamaClient"]
