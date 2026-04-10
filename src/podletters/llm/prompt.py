"""System and user prompt templates for podcast transcript generation.

Mirrors PRD §12.1 exactly. The templates are plain strings so they
can be unit-tested and iterated on without touching the Ollama client.
"""

from __future__ import annotations

from podletters.llm.ollama_client import ChatMessage
from podletters.models import NewsletterPayload

SYSTEM_PROMPT = """\
You are an expert German podcast scriptwriter. Your job is to transform \
newsletter content into a natural, engaging German-language podcast conversation.

HOSTS:
- [HOST1] Kai: analytical, calm, structured. Introduces topics, provides context.
- [HOST2] Mia: curious, warm, enthusiastic. Reacts, asks questions, adds perspective.

RULES:
1. Write 100% in German. Translate all source content.
2. Use natural spoken German — contractions, filler words, reactions are welcome.
3. Each speaker turn: 1–4 sentences maximum.
4. Alternate speakers regularly. Avoid monologues longer than 3 consecutive turns.
5. Do NOT invent facts. Stick to what is in the newsletter.
6. Begin with a greeting/welcome. End with a short outro (30–60 words).
7. Aim for 5–10 minutes of audio (approximately 800–1200 words of dialogue).
8. Return ONLY the dialogue. One line per turn. Format: [HOST1] text or [HOST2] text.
9. Generate an episode title (max 80 chars) and a 1–2 sentence description.

OUTPUT FORMAT:
TITLE: <episode title>
DESCRIPTION: <1-2 sentence description>
---
[HOST1] ...
[HOST2] ...\
"""

_USER_TEMPLATE = """\
Here is today's newsletter content. Convert it into a podcast script:

SOURCE: {sender_name}
DATE: {received_at}

{body_text}\
"""


def build_user_prompt(payload: NewsletterPayload) -> str:
    """Format the user message from a :class:`NewsletterPayload`."""
    return _USER_TEMPLATE.format(
        sender_name=payload.sender_name or payload.sender,
        received_at=payload.received_at.strftime("%Y-%m-%d"),
        body_text=payload.body_text,
    )


def build_messages(payload: NewsletterPayload) -> list[ChatMessage]:
    """Return the complete ``[system, user]`` message list for Ollama."""
    return [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=build_user_prompt(payload)),
    ]


__all__ = ["SYSTEM_PROMPT", "build_messages", "build_user_prompt"]
