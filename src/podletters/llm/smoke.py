"""Manual smoke test for the LLM transcript generation stack.

Run as::

    python -m podletters.llm.smoke [path/to/newsletter.txt]

If no path is given, a small built-in sample newsletter is used. The script
sends it through the prompt builder → Ollama → parser pipeline and prints
the resulting TranscriptPayload as formatted JSON.

Exit codes:
    0  transcript generated successfully
    1  parse error (LLM returned unparseable output)
    2  fatal error (Ollama unreachable, timeout, …)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from podletters.llm.ollama_client import OllamaClient
from podletters.llm.parser import TranscriptParseError, parse_llm_output
from podletters.llm.prompt import build_messages
from podletters.models import NewsletterPayload

_SAMPLE_NEWSLETTER = """\
TLDR Newsletter — April 7, 2026

BIG TECH & STARTUPS

OpenAI Released GPT-5 — OpenAI launched GPT-5 today. The new model is 3x
faster and 40% cheaper than GPT-4o. Early benchmarks show significant
improvements on coding and math tasks.

Google DeepMind Publishes Gemini 3 Paper — DeepMind shared details on
Gemini 3, their next-generation multimodal model. It supports 2M token
context and natively processes video.

AI & MACHINE LEARNING

Meta Open-Sources Llama 4 — Meta released Llama 4 with 120B parameters
under an open license. The model matches GPT-4o on most benchmarks and
runs on a single A100 GPU with 4-bit quantization.
"""


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
    )
    log = logging.getLogger("podletters.llm.smoke")

    # Load newsletter body.
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            log.error("File not found: %s", path)
            return 2
        body_text = path.read_text(encoding="utf-8")
        source = path.name
    else:
        body_text = _SAMPLE_NEWSLETTER
        source = "built-in sample"

    log.info("Using newsletter source: %s (%d chars)", source, len(body_text))

    payload = NewsletterPayload(
        message_id="<smoke-test@localhost>",
        sender="smoke@localhost",
        sender_name="Smoke Test",
        subject="LLM Smoke Test",
        received_at=datetime.now(timezone.utc),
        body_text=body_text,
    )

    messages = build_messages(payload)
    log.info("System prompt: %d chars", len(messages[0].content))
    log.info("User prompt: %d chars", len(messages[1].content))

    try:
        client = OllamaClient()
        response = client.chat(messages)
    except Exception as exc:
        log.error("Ollama call failed: %s", exc)
        return 2

    log.info("Raw LLM output (%d chars):", len(response.content))
    print("\n--- RAW LLM OUTPUT ---")
    print(response.content)
    print("--- END RAW OUTPUT ---\n")

    try:
        transcript = parse_llm_output(response.content)
    except TranscriptParseError as exc:
        log.error("Parse error: %s", exc)
        return 1

    print("--- PARSED TRANSCRIPT ---")
    print(json.dumps(transcript.model_dump(), indent=2, ensure_ascii=False))
    print("--- END TRANSCRIPT ---")
    log.info(
        "Success: title=%r, segments=%d",
        transcript.episode_title,
        len(transcript.segments),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - manual tool
    sys.exit(main())
