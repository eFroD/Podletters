"""Tests for podletters.llm.prompt."""

from __future__ import annotations

from datetime import datetime, timezone

from podletters.llm.prompt import SYSTEM_PROMPT, build_messages, build_user_prompt
from podletters.models import NewsletterPayload


def _sample_payload() -> NewsletterPayload:
    return NewsletterPayload(
        message_id="<id@x.com>",
        sender="tldr@example.com",
        sender_name="TLDR",
        subject="TLDR 2026-04-07",
        received_at=datetime(2026, 4, 7, 8, 0, tzinfo=timezone.utc),
        body_text="OpenAI released GPT-5 today. It is faster and cheaper.",
    )


def test_system_prompt_contains_host_definitions() -> None:
    assert "[HOST1]" in SYSTEM_PROMPT
    assert "[HOST2]" in SYSTEM_PROMPT
    assert "Kai" in SYSTEM_PROMPT
    assert "Mia" in SYSTEM_PROMPT


def test_system_prompt_contains_output_format() -> None:
    assert "TITLE:" in SYSTEM_PROMPT
    assert "DESCRIPTION:" in SYSTEM_PROMPT
    assert "---" in SYSTEM_PROMPT


def test_build_user_prompt_includes_payload_fields() -> None:
    payload = _sample_payload()
    prompt = build_user_prompt(payload)
    assert "TLDR" in prompt
    assert "2026-04-07" in prompt
    assert "GPT-5" in prompt


def test_build_user_prompt_falls_back_to_sender_address() -> None:
    payload = NewsletterPayload(
        message_id="<id@x.com>",
        sender="tldr@example.com",
        sender_name="",
        subject="s",
        received_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
        body_text="content",
    )
    prompt = build_user_prompt(payload)
    assert "tldr@example.com" in prompt


def test_build_messages_returns_system_and_user() -> None:
    msgs = build_messages(_sample_payload())
    assert len(msgs) == 2
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert msgs[0].content == SYSTEM_PROMPT
    assert "GPT-5" in msgs[1].content
