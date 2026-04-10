"""Tests for podletters.llm.parser."""

from __future__ import annotations

import pytest

from podletters.llm.parser import TranscriptParseError, parse_llm_output

GOOD_OUTPUT = """\
TITLE: TLDR: KI-Trends – 7. April 2026
DESCRIPTION: Heute sprechen wir über die neuesten KI-Entwicklungen.
---
[HOST1] Willkommen zu unserem Podcast! Heute haben wir einige spannende Themen.
[HOST2] Genau, lass uns direkt einsteigen.
[HOST1] Das erste Thema dreht sich um neue Sprachmodelle.
[HOST2] Oh ja, da hat sich einiges getan!
"""

GOOD_WITH_BLANKS = """\
TITLE: Test Episode

DESCRIPTION: Beschreibung der Episode.

---

[HOST1] Hallo zusammen.

[HOST2] Hallo!
"""


def test_parse_happy_path() -> None:
    result = parse_llm_output(GOOD_OUTPUT)
    assert result.episode_title == "TLDR: KI-Trends – 7. April 2026"
    assert "KI-Entwicklungen" in result.episode_description
    assert len(result.segments) == 4
    assert result.segments[0].speaker == "HOST1"
    assert result.segments[1].speaker == "HOST2"
    assert "Willkommen" in result.segments[0].text


def test_parse_handles_blank_lines() -> None:
    result = parse_llm_output(GOOD_WITH_BLANKS)
    assert result.episode_title == "Test Episode"
    assert len(result.segments) == 2


def test_parse_missing_title() -> None:
    bad = """\
DESCRIPTION: Beschreibung.
---
[HOST1] Hallo.
"""
    with pytest.raises(TranscriptParseError, match="Missing TITLE"):
        parse_llm_output(bad)


def test_parse_missing_description() -> None:
    bad = """\
TITLE: Test
---
[HOST1] Hallo.
"""
    with pytest.raises(TranscriptParseError, match="Missing DESCRIPTION"):
        parse_llm_output(bad)


def test_parse_no_segments() -> None:
    bad = """\
TITLE: Test
DESCRIPTION: Beschreibung.
---
This line has no speaker tag.
Neither does this one.
"""
    with pytest.raises(TranscriptParseError, match="No valid"):
        parse_llm_output(bad)


def test_parse_no_separator() -> None:
    bad = """\
TITLE: Test
DESCRIPTION: Beschreibung.
[HOST1] Hallo.
"""
    # Without '---', parser never enters dialogue mode → no segments.
    with pytest.raises(TranscriptParseError, match="No valid"):
        parse_llm_output(bad)


def test_parse_skips_junk_lines_in_dialogue() -> None:
    raw = """\
TITLE: Test
DESCRIPTION: Desc.
---
[HOST1] Hallo.
(some stage direction)
[HOST2] Hi!
"""
    result = parse_llm_output(raw)
    assert len(result.segments) == 2


def test_parse_case_insensitive_headers() -> None:
    raw = """\
title: Mein Titel
description: Meine Beschreibung.
---
[HOST1] Hallo.
"""
    result = parse_llm_output(raw)
    assert result.episode_title == "Mein Titel"
    assert result.episode_description == "Meine Beschreibung."
