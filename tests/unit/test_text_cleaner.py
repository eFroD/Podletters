"""Tests for podletters.ingestion.text_cleaner."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from podletters.ingestion.imap_client import FetchedEmail
from podletters.ingestion.text_cleaner import clean_body, to_payload


SAMPLE_PLAIN = """\
TLDR Newsletter — 7 April 2026

Top story: a new open-source LLM was released today.

It scores 82 on MMLU and runs on a single GPU.

---
Unsubscribe from this list
View this email in your browser
© 2026 TLDR
"""


SAMPLE_HTML = """\
<html><body>
  <h1>TLDR Newsletter</h1>
  <p>OpenAI released GPT-5 today. It is faster and cheaper.</p>
  <p>Read more in our <a href="https://x.com">deep dive</a>.</p>
  <img src="https://track.example.com/pixel.gif" width="1" height="1"/>
  <footer>
    <a href="https://x.com/unsub">Unsubscribe</a> |
    <a href="https://x.com/view">View this email in your browser</a>
  </footer>
</body></html>
"""


def test_clean_body_prefers_plain_text() -> None:
    out = clean_body(SAMPLE_PLAIN, "<p>ignored</p>")
    assert "TLDR Newsletter" in out
    assert "Top story" in out
    assert "Unsubscribe" not in out
    assert "View this email" not in out
    assert "©" not in out


def test_clean_body_collapses_blank_runs() -> None:
    text = "line1\n\n\n\nline2\n\n\nline3"
    out = clean_body(text, None)
    assert out == "line1\n\nline2\n\nline3"


def test_clean_body_falls_back_to_html() -> None:
    out = clean_body("", SAMPLE_HTML)
    assert "GPT-5" in out
    assert "Unsubscribe" not in out
    assert "View this email" not in out


def test_clean_body_empty_inputs() -> None:
    assert clean_body("", "") == ""
    assert clean_body(None, None) == ""


def test_to_payload_happy_path() -> None:
    email = FetchedEmail(
        message_id="<id@x.com>",
        sender="tldr@example.com",
        sender_name="TLDR",
        subject="TLDR — 7 April 2026",
        received_at=datetime(2026, 4, 7, 8, 0, tzinfo=timezone.utc),
        body_text=SAMPLE_PLAIN,
        body_html="",
    )
    payload = to_payload(email)
    assert payload.sender == "tldr@example.com"
    assert "Top story" in payload.body_text
    assert "Unsubscribe" not in payload.body_text


def test_to_payload_raises_on_empty_body() -> None:
    email = FetchedEmail(
        message_id="<id@x.com>",
        sender="tldr@example.com",
        sender_name="TLDR",
        subject="x",
        received_at=datetime(2026, 4, 7, 8, 0, tzinfo=timezone.utc),
        body_text="",
        body_html="",
    )
    with pytest.raises(ValueError):
        to_payload(email)
