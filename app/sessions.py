"""Per-session bookkeeping and fresh-agent construction.

Every request rebuilds the requested agent from the compose config, because a
Strands ``Agent`` raises ``ConcurrencyException`` when invoked twice in
parallel. TTL and exchange counts are tracked in-process, keyed by session id.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from app.config import COMPOSE_CONFIG, get_web_settings

logger = logging.getLogger(__name__)


@dataclass
class _SessionEntry:
    """One conversation session's bookkeeping.

    Attributes:
        max_exchanges: Question budget before the session resets.
        created_at: Unix time the session was created.
        last_used: Unix time of the last activity.
        exchange_count: Completed question/answer exchanges.
    """

    max_exchanges: int
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    exchange_count: int = 0


_sessions: dict[str, _SessionEntry] = {}
_lock = Lock()


def _build_fresh_agent(agent_name: str, session_id: str) -> Any:
    """Resolve the compose config and return one agent by name.

    Args:
        agent_name: Key in the compose ``agents`` block (``searcher`` or
            ``redactor``).
        session_id: Forwarded to ``load`` so the file session manager, if any,
            rehydrates history for this session.

    Returns:
        A freshly built Strands ``Agent``.

    Raises:
        KeyError: When ``agent_name`` is not defined in the compose config.
    """
    from strands_compose import load

    resolved = load(COMPOSE_CONFIG, session_id=session_id)
    if agent_name not in resolved.agents:
        raise KeyError(f"agent {agent_name!r} is not defined in the compose config")
    return resolved.agents[agent_name]


def _cleanup_stale() -> None:
    """Evict sessions idle longer than the TTL. Caller holds the lock."""
    ttl = get_web_settings().session_ttl_seconds
    now = time.time()
    stale = [sid for sid, e in _sessions.items() if now - e.last_used > ttl]
    for sid in stale:
        logger.info("session_id=<%s> | evicting stale session", sid)
        del _sessions[sid]


def _session_info(session_id: str, entry: _SessionEntry) -> dict[str, Any]:
    """Build the session-status payload the frontend shows.

    Args:
        session_id: The session identifier.
        entry: Its bookkeeping entry.

    Returns:
        A JSON-serialisable status dict.
    """
    ttl = get_web_settings().session_ttl_seconds
    expires_at = entry.last_used + ttl
    return {
        "sessionId": session_id,
        "exchangeCount": entry.exchange_count,
        "maxExchanges": entry.max_exchanges,
        "remaining": max(0, entry.max_exchanges - entry.exchange_count),
        "ttlRemaining": max(0, int(expires_at - time.time())),
    }


def get_or_create_agent(session_id: str, agent_name: str) -> tuple[Any, dict[str, Any]]:
    """Return a fresh agent plus the current session status.

    Bookkeeping is per session id; the agent is rebuilt each call to avoid
    Strands' ConcurrencyException.

    Args:
        session_id: The conversation's session id.
        agent_name: Which compose agent to build.

    Returns:
        A tuple of the agent and its session-status dict.
    """
    settings = get_web_settings()
    with _lock:
        _cleanup_stale()
        now = time.time()
        entry = _sessions.get(session_id)
        if entry is None or entry.exchange_count >= entry.max_exchanges:
            entry = _SessionEntry(max_exchanges=settings.max_exchanges, created_at=now)
            _sessions[session_id] = entry
        else:
            entry.last_used = now

    agent = _build_fresh_agent(agent_name, session_id)
    return agent, _session_info(session_id, entry)


def record_exchange(session_id: str) -> dict[str, Any] | None:
    """Count one completed exchange and return the updated status.

    Args:
        session_id: The session to update.

    Returns:
        The updated status, or None when the session is unknown.
    """
    with _lock:
        entry = _sessions.get(session_id)
        if entry is None:
            return None
        entry.exchange_count += 1
        entry.last_used = time.time()
        return _session_info(session_id, entry)


def reset_session(session_id: str) -> bool:
    """Drop one session's bookkeeping.

    Args:
        session_id: The session to remove.

    Returns:
        True when a session was removed.
    """
    with _lock:
        return _sessions.pop(session_id, None) is not None


def get_session_info(session_id: str) -> dict[str, Any] | None:
    """Return a session's status without creating one.

    Args:
        session_id: The session to read.

    Returns:
        The status, or None when the session is unknown.
    """
    with _lock:
        entry = _sessions.get(session_id)
        return _session_info(session_id, entry) if entry else None
