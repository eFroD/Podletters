"""Tests for podletters.llm.ollama_client."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from podletters.llm.ollama_client import ChatMessage, OllamaClient


@pytest.fixture()
def client() -> OllamaClient:
    """Build an OllamaClient without touching Settings / .env."""
    with patch("podletters.llm.ollama_client.get_settings") as mock:
        mock.return_value.ollama_base_url = "http://localhost:11434"
        mock.return_value.ollama_model = "test-model"
        mock.return_value.ollama_timeout_seconds = 30
        return OllamaClient()


def _ollama_response(content: str = "reply") -> dict:
    return {
        "model": "test-model",
        "message": {"role": "assistant", "content": content},
        "total_duration": 2_000_000_000,
        "eval_count": 42,
    }


def test_chat_sends_correct_payload(client: OllamaClient, httpx_mock) -> None:
    httpx_mock.add_response(json=_ollama_response("Hallo"))
    messages = [
        ChatMessage(role="system", content="You are helpful."),
        ChatMessage(role="user", content="Hi"),
    ]
    result = client.chat(messages)

    assert result.content == "Hallo"
    assert result.model == "test-model"
    assert result.eval_count == 42
    assert result.total_duration_ns == 2_000_000_000

    # Verify the outgoing request payload.
    req = httpx_mock.get_request()
    body = json.loads(req.content)
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["keep_alive"] == 0
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"


def test_chat_raises_on_http_error(client: OllamaClient, httpx_mock) -> None:
    httpx_mock.add_response(status_code=500, text="boom")
    with pytest.raises(Exception):
        client.chat([ChatMessage(role="user", content="x")])


def test_chat_model_override(client: OllamaClient, httpx_mock) -> None:
    httpx_mock.add_response(json=_ollama_response())
    client.chat([ChatMessage(role="user", content="x")], model="other-model")
    body = json.loads(httpx_mock.get_request().content)
    assert body["model"] == "other-model"


@pytest.fixture()
def httpx_mock():
    """Minimal httpx mock using pytest-httpx-style patching via respx."""
    # We build a thin mock without requiring pytest-httpx as a dependency.
    import httpx as _httpx

    class _Mock:
        def __init__(self) -> None:
            self._responses: list[_httpx.Response] = []
            self._requests: list[_httpx.Request] = []

        def add_response(
            self,
            *,
            status_code: int = 200,
            json: dict | None = None,
            text: str | None = None,
        ) -> None:
            if json is not None:
                import json as _json

                content = _json.dumps(json).encode()
                headers = {"content-type": "application/json"}
            else:
                content = (text or "").encode()
                headers = {"content-type": "text/plain"}
            self._responses.append(
                _httpx.Response(status_code, content=content, headers=headers)
            )

        def get_request(self) -> _httpx.Request:
            assert self._requests, "No requests recorded"
            return self._requests[-1]

        def _transport(self) -> _httpx.MockTransport:
            responses = iter(self._responses)
            requests = self._requests

            def handler(request: _httpx.Request) -> _httpx.Response:
                requests.append(request)
                return next(responses)

            return _httpx.MockTransport(handler)

    mock = _Mock()
    transport = mock._transport()
    original_post = _httpx.post

    def patched_post(url, **kwargs):
        client = _httpx.Client(transport=transport)
        return client.post(url, **kwargs)

    with patch.object(_httpx, "post", patched_post):
        yield mock
