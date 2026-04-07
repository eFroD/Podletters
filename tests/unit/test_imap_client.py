"""Tests for podletters.ingestion.imap_client."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from podletters.ingestion.imap_client import (
    FetchedEmail,
    _normalize_whitelist,
    fetch_new_emails,
)


def _fake_msg(
    *,
    sender: str,
    name: str = "",
    msg_id: str = "<id@example.com>",
    subject: str = "Hello",
    text: str = "body",
) -> SimpleNamespace:
    return SimpleNamespace(
        uid="1",
        from_=sender,
        from_values=SimpleNamespace(name=name),
        subject=subject,
        date=datetime(2026, 4, 7, 8, 0, tzinfo=timezone.utc),
        text=text,
        html="",
        headers={"message-id": (msg_id,)},
    )


def test_normalize_whitelist_lowercases_and_dedupes() -> None:
    assert _normalize_whitelist(["A@x.com", " a@X.com ", ""]) == {"a@x.com"}


def test_from_mail_message_lowercases_sender() -> None:
    msg = _fake_msg(sender="TLDR@Example.com", name="TLDR")
    fetched = FetchedEmail.from_mail_message(msg)  # type: ignore[arg-type]
    assert fetched.sender == "tldr@example.com"
    assert fetched.sender_name == "TLDR"
    assert fetched.message_id == "<id@example.com>"


def test_fetch_new_emails_filters_by_whitelist() -> None:
    msgs = [
        _fake_msg(sender="tldr@example.com"),
        _fake_msg(sender="other@example.com"),
    ]
    fake_mailbox = MagicMock()
    fake_mailbox.fetch.return_value = iter(msgs)
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_mailbox
    fake_ctx.__exit__.return_value = False

    settings = SimpleNamespace(
        imap_host="h",
        imap_port=993,
        imap_user="u",
        imap_password="p",
        imap_folder="INBOX",
        sender_whitelist=["tldr@example.com"],
    )

    with patch("podletters.ingestion.imap_client.MailBox") as mailbox_cls:
        mailbox_cls.return_value.login.return_value = fake_ctx
        result = fetch_new_emails(settings)  # type: ignore[arg-type]

    assert len(result) == 1
    assert result[0].sender == "tldr@example.com"


def test_fetch_new_emails_empty_whitelist_returns_nothing() -> None:
    settings = SimpleNamespace(
        imap_host="h",
        imap_port=993,
        imap_user="u",
        imap_password="p",
        imap_folder="INBOX",
        sender_whitelist=[],
    )
    assert fetch_new_emails(settings) == []  # type: ignore[arg-type]
