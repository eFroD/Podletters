"""Parse raw LLM output into a :class:`~podletters.models.TranscriptPayload`.

Implements the parsing logic from PRD §12.2 with stricter validation:
missing TITLE, DESCRIPTION or the ``---`` separator raise
:class:`TranscriptParseError` so the caller can decide on a retry or
fallback strategy.
"""

from __future__ import annotations

import logging
import re

from podletters.models import TranscriptPayload, TranscriptSegment

logger = logging.getLogger(__name__)

_SPEAKER_RE = re.compile(r"^\[(HOST[12])\]\s+(.+)")


class TranscriptParseError(ValueError):
    """Raised when LLM output cannot be parsed into a valid transcript."""


def parse_llm_output(raw: str) -> TranscriptPayload:
    """Parse the raw LLM response into a structured transcript.

    Expected format::

        TITLE: <episode title>
        DESCRIPTION: <1-2 sentence description>
        ---
        [HOST1] ...
        [HOST2] ...

    Raises
    ------
    TranscriptParseError
        If title, description or dialogue separator is missing, or if no
        valid speaker segments are found.
    """
    lines = raw.strip().splitlines()
    title = ""
    description = ""
    segments: list[TranscriptSegment] = []
    in_dialogue = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not in_dialogue:
            if stripped.upper().startswith("TITLE:"):
                title = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("DESCRIPTION:"):
                description = stripped.split(":", 1)[1].strip()
            elif stripped == "---":
                in_dialogue = True
        else:
            match = _SPEAKER_RE.match(stripped)
            if match:
                segments.append(
                    TranscriptSegment(
                        speaker=match.group(1),  # type: ignore[arg-type]
                        text=match.group(2).strip(),
                    )
                )
            else:
                logger.debug("Skipping non-dialogue line: %s", stripped[:80])

    if not title:
        raise TranscriptParseError("Missing TITLE in LLM output")
    if not description:
        raise TranscriptParseError("Missing DESCRIPTION in LLM output")
    if not segments:
        raise TranscriptParseError("No valid [HOST1]/[HOST2] segments found after '---'")

    logger.info(
        "Parsed transcript: title=%r, segments=%d",
        title[:60],
        len(segments),
    )
    return TranscriptPayload(
        episode_title=title,
        episode_description=description,
        segments=segments,
    )


__all__ = ["TranscriptParseError", "parse_llm_output"]
