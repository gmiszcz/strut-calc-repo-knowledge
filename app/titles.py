"""Conversation title generation via a direct Bedrock ``converse`` call.

Bypasses strands on purpose: a title is one short, tool-less completion, so a
plain boto3 call to the same Haiku model is cheaper and faster than building an
agent.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from src.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You name saved conversations about a CAE codebase. Reply with ONLY a short, "
    "specific title of 3 to 8 words that describes the topic. No quotes, no "
    "trailing punctuation, no prefix like 'Title:'. Use the language of the "
    "user's questions."
)

# Per-turn text limits keep the title request small and cheap.
_MAX_TURNS = 4
_QUESTION_CHARS = 500
_ANSWER_CHARS = 800
_TITLE_CHARS = 80


@lru_cache(maxsize=1)
def _client() -> Any:
    """Return a cached Bedrock runtime client built from the engine settings.

    Returns:
        A boto3 ``bedrock-runtime`` client.
    """
    settings = get_settings()
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    return session.client(
        "bedrock-runtime",
        config=Config(retries={"max_attempts": 3, "mode": "adaptive"}),
    )


def fallback_title(turns: list[dict[str, Any]]) -> str:
    """Build a title from the first question when the model is unavailable.

    Args:
        turns: The conversation turns (``question``/``answer`` dicts).

    Returns:
        The first question, trimmed to the title length limit.
    """
    first = next((str(t.get("question", "")).strip() for t in turns if t.get("question")), "")
    if not first:
        return "Untitled conversation"
    first = " ".join(first.split())
    return first if len(first) <= _TITLE_CHARS else first[: _TITLE_CHARS - 1].rstrip() + "…"


def generate_title(turns: list[dict[str, Any]]) -> str:
    """Ask the chat model for a short title describing the conversation.

    Args:
        turns: The conversation turns (``question``/``answer`` dicts).

    Returns:
        The generated title, or a title from the first question when the call
        fails or returns nothing.
    """
    parts = []
    for i, turn in enumerate(turns[:_MAX_TURNS], start=1):
        question = str(turn.get("question", ""))[:_QUESTION_CHARS]
        answer = str(turn.get("answer", ""))[:_ANSWER_CHARS]
        parts.append(f"Q{i}: {question}\nA{i}: {answer}")
    transcript = "\n\n".join(parts)

    try:
        response = _client().converse(
            modelId=get_settings().agent_model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": transcript}]}],
            inferenceConfig={"maxTokens": 40},
        )
    except Exception:  # noqa: BLE001 - a title must never block saving
        logger.warning("title generation failed, using the first question", exc_info=True)
        return fallback_title(turns)

    blocks = response.get("output", {}).get("message", {}).get("content", [])
    text = " ".join(b["text"] for b in blocks if "text" in b).strip().strip("\"'").strip()
    if not text:
        return fallback_title(turns)
    text = " ".join(text.split())
    return text[:_TITLE_CHARS]
