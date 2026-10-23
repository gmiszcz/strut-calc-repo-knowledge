"""Streaming callback handler — forwards Strands events to an asyncio queue.

The handler runs on the agent's worker thread and hands events to the request's
event loop thread-safely. Event shapes match what the frontend consumer expects
(tool_start / tool_update / result_ready / reasoning / text).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Friendly label per tool name. The search tool arrives prefixed `kb_`.
_TOOL_META: dict[str, tuple[str, str]] = {
    "kb_search_code": ("pi-search", "Searching the codebase"),
}


def _label(name: str, inp: dict[str, Any] | None) -> tuple[str, str]:
    """Return an (icon, text) label for a tool call.

    Args:
        name: The tool name.
        inp: Parsed tool input, when available, to refine the label with the
            query being searched.

    Returns:
        An icon class and human-readable text.
    """
    icon, text = _TOOL_META.get(name, ("pi-cog", f"Calling {name}"))
    if name == "kb_search_code" and isinstance(inp, dict):
        query = inp.get("query")
        if query:
            text = f"Searching: {query}"
    return icon, text


class StreamingCallbackHandler:
    """Pushes Strands Agent events onto an ``asyncio.Queue`` for SSE."""

    def __init__(
        self,
        queue: asyncio.Queue[dict[str, Any]],
        loop: asyncio.AbstractEventLoop,
        stage: str,
    ) -> None:
        """Bind the handler to a queue, the request's event loop, and a stage.

        Args:
            queue: Queue the SSE generator drains.
            loop: The event loop the queue belongs to.
            stage: Stage tag added to every emitted event (``searcher`` or
                ``redactor``), so the frontend can route it to the right panel.
        """
        self._queue = queue
        self._loop = loop
        self._stage = stage
        self._pending_tool: str | None = None
        self._pending_input = ""

    def _put(self, event: dict[str, Any]) -> None:
        """Tag one event with its stage and hand it to the loop thread-safely.

        Args:
            event: The SSE event payload.
        """
        event["stage"] = self._stage
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def __call__(self, **kwargs: Any) -> None:
        """Receive one Strands streaming callback and forward it.

        Args:
            **kwargs: The Strands callback payload (event dict, data tokens,
                reasoning text, tool result).
        """
        event = kwargs.get("event", {}) or {}

        tool_use = event.get("contentBlockStart", {}).get("start", {}).get("toolUse")
        if tool_use:
            name = tool_use.get("name", "unknown")
            self._pending_tool = name
            self._pending_input = ""
            icon, text = _label(name, tool_use.get("input", {}))
            self._put({"type": "tool_start", "icon": icon, "text": text})

        delta_tool = event.get("contentBlockDelta", {}).get("delta", {}).get("toolUse")
        if delta_tool and "input" in delta_tool:
            self._pending_input += delta_tool["input"]

        if "contentBlockStop" in event and self._pending_tool and self._pending_input:
            try:
                inp = json.loads(self._pending_input)
            except (json.JSONDecodeError, TypeError):
                inp = None
            if inp is not None:
                icon, text = _label(self._pending_tool, inp)
                self._put({"type": "tool_update", "icon": icon, "text": text})

        reasoning = kwargs.get("reasoningText", "")
        if reasoning:
            self._put({"type": "reasoning", "text": reasoning})

        data = kwargs.get("data", "")
        if data:
            self._put({"type": "text", "text": data})

        if kwargs.get("result") is not None:
            self._put({"type": "result_ready"})
            self._pending_tool = None
            self._pending_input = ""
