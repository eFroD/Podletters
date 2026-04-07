"""Convert raw newsletter bodies to clean plain text.

Implements FR-01.4 and FR-01.5: prefer ``text/plain`` if available, otherwise
extract readable text from the HTML body via trafilatura (with html2text as a
fallback). Strips common footer junk: unsubscribe lines, view-in-browser
links, tracking pixels and excessive whitespace.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from podletters.ingestion.imap_client import FetchedEmail
from podletters.models import NewsletterPayload

logger = logging.getLogger(__name__)

# Patterns matched against entire stripped lines (case-insensitive).
_FOOTER_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^unsubscribe\b.*", re.IGNORECASE),
    re.compile(r".*\bunsubscribe\b.*", re.IGNORECASE),
    re.compile(r".*view\s+(this\s+)?(email|message)\s+in\s+(your\s+)?browser.*", re.IGNORECASE),
    re.compile(r".*manage\s+(your\s+)?(subscription|preferences).*", re.IGNORECASE),
    re.compile(r".*forward(ed)?\s+to\s+a\s+friend.*", re.IGNORECASE),
    re.compile(r"^©.*", re.IGNORECASE),
    re.compile(r"^copyright\b.*", re.IGNORECASE),
    re.compile(r"^you\s+(are\s+)?receiv(ed|ing).*", re.IGNORECASE),
    re.compile(r"^sent\s+to\s+.*", re.IGNORECASE),
)

# Strip standalone tracking-pixel / 1x1-image style HTML remnants if any
# survive trafilatura (rare but cheap to guard against).
_TRACKING_PIXEL_RE = re.compile(
    r"<img[^>]*(?:width=['\"]?1['\"]?|height=['\"]?1['\"]?)[^>]*>",
    re.IGNORECASE,
)


def _extract_from_html(html: str) -> str:
    """Convert HTML to readable plain text. Tries trafilatura, then html2text."""
    if not html:
        return ""

    # Drop obvious tracking pixels before parsing.
    html = _TRACKING_PIXEL_RE.sub("", html)

    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            include_links=False,
            favor_precision=True,
        )
        if extracted:
            return extracted
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("trafilatura extraction failed: %s", exc)

    try:
        import html2text

        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0
        return h.handle(html)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("html2text fallback failed: %s", exc)
        return ""


def _drop_footer_lines(text: str) -> str:
    """Remove unsubscribe/footer noise and collapse blank-line runs."""
    cleaned: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if any(pat.match(line) for pat in _FOOTER_LINE_PATTERNS):
            continue
        cleaned.append(line)

    # Collapse runs of blank lines and trim leading/trailing whitespace.
    out: list[str] = []
    blank = False
    for line in cleaned:
        if not line:
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(line)
            blank = False
    return "\n".join(out).strip()


def clean_body(text: str | None, html: str | None) -> str:
    """Return cleaned plain-text body, preferring ``text/plain`` (FR-01.5)."""
    base = (text or "").strip()
    if not base:
        base = _extract_from_html(html or "")
    return _drop_footer_lines(base)


def to_payload(email: FetchedEmail) -> NewsletterPayload:
    """Convert a :class:`FetchedEmail` to a validated :class:`NewsletterPayload`.

    Raises ``ValueError`` if the cleaned body is empty (which would otherwise
    fail Pydantic validation downstream).
    """
    body = clean_body(email.body_text, email.body_html)
    if not body:
        raise ValueError(f"Empty body after cleaning for message {email.message_id!r}")

    received = email.received_at
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)

    return NewsletterPayload(
        message_id=email.message_id,
        sender=email.sender,
        sender_name=email.sender_name,
        subject=email.subject,
        received_at=received,
        body_text=body,
    )


__all__ = ["clean_body", "to_payload"]


def _utc_now() -> datetime:  # pragma: no cover - trivial
    return datetime.now(timezone.utc)
