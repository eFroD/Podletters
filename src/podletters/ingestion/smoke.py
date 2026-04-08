"""Manual smoke test for the ingestion stack.

Run as::

    python -m podletters.ingestion.smoke

Connects via IMAP using the settings in ``.env``, fetches unseen mail,
applies the sender whitelist, cleans bodies, and prints a summary plus
the first cleaned newsletter. This is the Phase 1 manual checkpoint
for the ingestion path — no LLM or TTS are involved.

Exit codes:
    0  at least one newsletter fetched and cleaned
    1  nothing fetched (whitelist miss or empty inbox)
    2  fatal error (connection failure, bad config, …)
"""

from __future__ import annotations

import logging
import sys
from textwrap import shorten

from podletters.ingestion.imap_client import fetch_new_emails
from podletters.ingestion.text_cleaner import to_payload


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
    )
    log = logging.getLogger("podletters.smoke")

    try:
        emails = fetch_new_emails()
    except Exception as exc:  # pragma: no cover - manual tool
        log.error("IMAP fetch failed: %s", exc)
        return 2

    if not emails:
        log.warning("No matching newsletters in inbox (empty or not whitelisted)")
        return 1

    log.info("Fetched %d newsletter(s):", len(emails))
    for i, email in enumerate(emails, 1):
        log.info(
            "  %d. [%s] %s — %s",
            i,
            email.sender,
            shorten(email.subject, width=60, placeholder="…"),
            email.received_at.isoformat(),
        )

    first = emails[0]
    try:
        payload = to_payload(first)
    except ValueError as exc:
        log.error("Cleaning produced empty body for %s: %s", first.message_id, exc)
        return 2

    print("\n" + "=" * 72)
    print(f"MESSAGE-ID : {payload.message_id}")
    print(f"FROM       : {payload.sender_name} <{payload.sender}>")
    print(f"SUBJECT    : {payload.subject}")
    print(f"RECEIVED   : {payload.received_at.isoformat()}")
    print(f"BODY CHARS : {len(payload.body_text)}")
    print("=" * 72)
    print(payload.body_text)
    print("=" * 72)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual tool
    sys.exit(main())
