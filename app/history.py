"""Saved conversation history: list, save, restore and delete.

Only conversations the user explicitly saves are stored, one JSON file per
session under ``<root>/.history``. The file id equals the chat session id, so
restoring a conversation reuses that id and the agents rehydrate their own
memory from the file session manager (``<root>/.sessions/session_<id>``).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import ROOT_DIR
from app.titles import generate_title

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["history"])

HISTORY_DIR = ROOT_DIR / ".history"
# Matches `session_manager.params.storage_dir` in agent/config.yaml.
AGENT_SESSIONS_DIR = ROOT_DIR / ".sessions"

# Session ids are client-side nanoids. Anything else is rejected so an id can
# never escape the history directory.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_lock = Lock()


class SavedTurn(BaseModel):
    """One question/answer exchange as the frontend renders it.

    Attributes:
        id: Client-side turn id.
        question: The question as the user typed it.
        answer: The redactor's Markdown answer.
        reasoning: Live-panel reasoning steps.
        live: The searcher's streamed draft.
    """

    id: str
    question: str
    answer: str = ""
    reasoning: list[dict[str, Any]] = Field(default_factory=list)
    live: str = ""


class SaveRequest(BaseModel):
    """Body of a /history/save request.

    Attributes:
        sessionId: The conversation's session id.
        turns: The conversation to store.
        sessionUsage: Token usage of the conversation so far.
    """

    sessionId: str
    turns: list[SavedTurn]
    sessionUsage: dict[str, int] = Field(default_factory=dict)


def _history_path(session_id: str) -> Path:
    """Return the history file path for a validated session id.

    Args:
        session_id: The session id to locate.

    Returns:
        The JSON file path inside the history directory.

    Raises:
        HTTPException: 400 when the id has an invalid format.
    """
    if not _ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session id.")
    return HISTORY_DIR / f"{session_id}.json"


def _read(path: Path) -> dict[str, Any]:
    """Read one history file.

    Args:
        path: The history file.

    Returns:
        The stored conversation.
    """
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    """Build the list-view summary of a stored conversation.

    Args:
        record: The stored conversation.

    Returns:
        Id, title, timestamps, turn count and token usage.
    """
    return {
        "id": record["id"],
        "title": record["title"],
        "createdAt": record["createdAt"],
        "savedAt": record["savedAt"],
        "turnCount": len(record.get("turns", [])),
        "sessionUsage": record.get("sessionUsage", {}),
    }


@router.get("")
def list_history() -> list[dict[str, Any]]:
    """List saved conversations, newest first.

    Returns:
        One summary per saved conversation.
    """
    if not HISTORY_DIR.is_dir():
        return []
    summaries = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            summaries.append(_summary(_read(path)))
        except (OSError, ValueError, KeyError):
            logger.warning("path=<%s> | skipping unreadable history file", path, exc_info=True)
    return sorted(summaries, key=lambda s: s["savedAt"], reverse=True)


@router.get("/{session_id}")
def get_history(session_id: str) -> dict[str, Any]:
    """Return one saved conversation in full.

    Args:
        session_id: The conversation to load.

    Returns:
        The stored conversation, including its turns.

    Raises:
        HTTPException: 404 when it is not saved.
    """
    path = _history_path(session_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _read(path)


@router.post("/save")
def save_history(req: SaveRequest) -> dict[str, Any]:
    """Save or update a conversation.

    The first save asks the chat model for a title. Later saves of the same
    session keep that title and only replace the turns.

    Args:
        req: The session id, its turns and usage.

    Returns:
        The summary of the saved conversation.

    Raises:
        HTTPException: 400 when there is nothing to save.
    """
    path = _history_path(req.sessionId.strip())
    if not req.turns:
        raise HTTPException(status_code=400, detail="Nothing to save yet.")

    turns = [t.model_dump() for t in req.turns]
    existing = _read(path) if path.is_file() else None
    title = existing["title"] if existing else generate_title(turns)
    now = time.time()
    record = {
        "id": req.sessionId.strip(),
        "title": title,
        "createdAt": existing["createdAt"] if existing else now,
        "savedAt": now,
        "turns": turns,
        "sessionUsage": req.sessionUsage,
    }

    with _lock:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    logger.info("session_id=<%s>, title=<%s> | conversation saved", record["id"], title)
    return _summary(record)


@router.delete("/{session_id}")
def delete_history(session_id: str) -> dict[str, bool]:
    """Delete a saved conversation and the agents' memory of it.

    Args:
        session_id: The conversation to delete.

    Returns:
        Whether a saved conversation was removed.
    """
    path = _history_path(session_id)
    with _lock:
        removed = path.is_file()
        path.unlink(missing_ok=True)
        agent_dir = AGENT_SESSIONS_DIR / f"session_{session_id}"
        if agent_dir.is_dir():
            shutil.rmtree(agent_dir)
    logger.info("session_id=<%s>, removed=<%s> | conversation deleted", session_id, removed)
    return {"deleted": removed}
