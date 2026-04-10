#!/usr/bin/env python3
"""Evaluate the podcast system prompt against newsletter fixtures.

Usage::

    # Evaluate all fixtures in the default directory:
    python scripts/eval_prompt.py

    # Evaluate a single file:
    python scripts/eval_prompt.py tests/fixtures/prompt_eval/sample_tldr.txt

    # Save results to a directory:
    python scripts/eval_prompt.py --out-dir results/

For each newsletter fixture the script:
1. Sends it through the prompt builder → Ollama → parser.
2. Prints a quality checklist (German content, segment count, title,
   alternation pattern, welcome/outro).
3. Optionally saves the raw LLM output and parsed transcript JSON.

This is a human-in-the-loop tool: read the output and decide if the
prompt needs tuning.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from podletters.llm.ollama_client import OllamaClient
from podletters.llm.parser import TranscriptParseError, parse_llm_output
from podletters.llm.prompt import build_messages
from podletters.models import NewsletterPayload

FIXTURES_DIR = Path("tests/fixtures/prompt_eval")


def _load_payload(path: Path) -> NewsletterPayload:
    return NewsletterPayload(
        message_id=f"<eval-{path.stem}@localhost>",
        sender="eval@localhost",
        sender_name=path.stem,
        subject=path.stem,
        received_at=datetime.now(timezone.utc),
        body_text=path.read_text(encoding="utf-8"),
    )


def _check_quality(raw: str, transcript) -> list[str]:
    """Run heuristic quality checks, return a list of issues."""
    issues = []

    # German content: at least 80% of segment text should contain common German words.
    german_markers = {"und", "der", "die", "das", "ist", "wir", "ein", "auch", "ich", "nicht"}
    total_words = 0
    german_hits = 0
    for seg in transcript.segments:
        words = seg.text.lower().split()
        total_words += len(words)
        german_hits += sum(1 for w in words if w in german_markers)
    if total_words > 0 and german_hits / total_words < 0.05:
        issues.append("LOW GERMAN: very few German function words detected")

    # Segment count.
    if len(transcript.segments) < 6:
        issues.append(f"FEW SEGMENTS: only {len(transcript.segments)} (target: 10–30)")
    if len(transcript.segments) > 60:
        issues.append(f"TOO MANY SEGMENTS: {len(transcript.segments)}")

    # Alternation.
    consecutive = 1
    max_consecutive = 1
    for i in range(1, len(transcript.segments)):
        if transcript.segments[i].speaker == transcript.segments[i - 1].speaker:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 1
    if max_consecutive > 3:
        issues.append(f"MONOLOGUE: {max_consecutive} consecutive turns by same speaker")

    # Welcome / outro.
    first_text = transcript.segments[0].text.lower() if transcript.segments else ""
    if not any(w in first_text for w in ("willkommen", "hallo", "guten", "hey")):
        issues.append("NO WELCOME: first segment lacks greeting")

    last_text = transcript.segments[-1].text.lower() if transcript.segments else ""
    if not any(w in last_text for w in ("tschüss", "bis", "danke", "nächst", "ciao")):
        issues.append("NO OUTRO: last segment lacks farewell")

    # Title length.
    if len(transcript.episode_title) > 80:
        issues.append(f"TITLE TOO LONG: {len(transcript.episode_title)} chars (max 80)")

    return issues


def evaluate_one(path: Path, client: OllamaClient, out_dir: Path | None) -> bool:
    """Evaluate one fixture. Returns True if no issues found."""
    print(f"\n{'=' * 60}")
    print(f"  Fixture: {path.name}")
    print(f"{'=' * 60}")

    payload = _load_payload(path)
    messages = build_messages(payload)

    t0 = time.monotonic()
    response = client.chat(messages)
    elapsed = time.monotonic() - t0

    print(f"  Ollama: {len(response.content)} chars in {elapsed:.1f}s")

    try:
        transcript = parse_llm_output(response.content)
    except TranscriptParseError as exc:
        print(f"  PARSE ERROR: {exc}")
        return False

    issues = _check_quality(response.content, transcript)

    print(f"  Title:    {transcript.episode_title}")
    print(f"  Segments: {len(transcript.segments)}")
    print(f"  Speakers: {sum(1 for s in transcript.segments if s.speaker == 'HOST1')} HOST1, "
          f"{sum(1 for s in transcript.segments if s.speaker == 'HOST2')} HOST2")

    if issues:
        print(f"  Issues ({len(issues)}):")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  Quality: ALL CHECKS PASSED")

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{path.stem}_raw.txt").write_text(response.content, encoding="utf-8")
        (out_dir / f"{path.stem}_parsed.json").write_text(
            json.dumps(transcript.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  Saved to: {out_dir}/")

    return len(issues) == 0


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="Evaluate podcast prompt on fixtures")
    parser.add_argument("files", nargs="*", type=Path, help="Newsletter text files")
    parser.add_argument("--out-dir", type=Path, help="Save raw + parsed output")
    args = parser.parse_args()

    files = args.files or sorted(FIXTURES_DIR.glob("*.txt"))
    if not files:
        print(f"No fixtures found in {FIXTURES_DIR}")
        return 1

    client = OllamaClient()
    results = [evaluate_one(f, client, args.out_dir) for f in files]

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{total} passed")
    print(f"{'=' * 60}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
