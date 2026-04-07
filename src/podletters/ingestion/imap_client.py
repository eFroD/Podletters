"""IMAP fetch + sender-whitelist filtering.

Thin wrapper around ``imap-tools`` that yields :class:`FetchedEmail` objects
ready to be cleaned and turned into a :class:`~podletters.models.NewsletterPayload`.
Implements the data side of FR-01.1, FR-01.2 and FR-01.5.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

from imap_tools import AND, MailBox, MailMessage

from podletters.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FetchedEmail:
    """Raw email pulled from IMAP, prior to text cleaning."""

    message_id: str
    sender: str
    sender_name: str
    subject: str
    received_at: datetime
    body_text: str
    body_html: str

    @classmethod
    def from_mail_message(cls, msg: MailMessage) -> "FetchedEmail":
        received = msg.date or datetime.now(timezone.utc)
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        return cls(
            message_id=(msg.headers.get("message-id", (msg.uid or "",))[0] or msg.uid or ""),
            sender=(msg.from_ or "").lower(),
            sender_name=msg.from_values.name if msg.from_values else "",
            subject=msg.subject or "",
            received_at=received,
            body_text=msg.text or "",
            body_html=msg.html or "",
        )


def _normalize_whitelist(whitelist: list[str]) -> set[str]:
    return {addr.strip().lower() for addr in whitelist if addr.strip()}


def fetch_new_emails(settings: Settings | None = None) -> list[FetchedEmail]:
    """Connect to IMAP, return unseen messages from whitelisted senders.

    Messages are marked as seen so subsequent polls do not refetch them. The
    Redis-backed dedup store (``ingestion.dedup``) provides the additional
    guarantee that the *same* message is never processed twice (FR-01.3).
    """
    settings = settings or get_settings()
    whitelist = _normalize_whitelist(settings.sender_whitelist)
    if not whitelist:
        logger.warning("SENDER_WHITELIST is empty; no emails will be fetched")
        return []

    results: list[FetchedEmail] = list(_iter_fetch(settings, whitelist))
    logger.info("Fetched %d newsletter(s) from IMAP", len(results))
    return results


def _iter_fetch(settings: Settings, whitelist: set[str]) -> Iterator[FetchedEmail]:
    with MailBox(settings.imap_host, port=settings.imap_port).login(
        settings.imap_user,
        settings.imap_password,
        initial_folder=settings.imap_folder,
    ) as mailbox:
        for msg in mailbox.fetch(AND(seen=False), mark_seen=True, bulk=True):
            sender = (msg.from_ or "").lower()
            if sender not in whitelist:
                logger.debug("Skipping non-whitelisted sender: %s", sender)
                continue
            yield FetchedEmail.from_mail_message(msg)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    logging.basicConfig(level=logging.INFO)
    for email in fetch_new_emails():
        print(f"[{email.sender}] {email.subject} ({email.received_at.isoformat()})")
