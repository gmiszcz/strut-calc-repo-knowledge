"""SSE endpoint driving the searcher -> redactor flow.

One request runs two agents in sequence and streams every stage:

1. `searcher` — runs the semantic search, streams its reasoning (tool calls)
   and a first draft answer. Reasoning events are tagged ``stage: "searcher"``.
2. `redactor` — takes the searcher's draft and streams a polished Markdown
   answer, tagged ``stage: "redactor"``.

Event shapes (one JSON object per ``data: ...`` line):
  * ``{"type":"session", "session":{...}}``
  * ``{"type":"stage_start", "stage":"searcher"|"redactor"}``
  * ``{"type":"tool_start"|"tool_update", "stage":"searcher", "icon":..., "text":...}``
  * ``{"type":"result_ready", "stage":"searcher"}``
  * ``{"type":"reasoning", "stage":"searcher", "text":...}``
  * ``{"type":"text", "stage":"searcher"|"redactor", "text":...}``
  * ``{"type":"stage_complete", "stage":"searcher"|"redactor", "content":...}``
  * ``{"type":"complete", "session":{...}}``
  * ``{"type":"error", "error":...}``

The frontend puts ``stage:"searcher"`` events in the live/SSE panel and the
``stage:"redactor"`` output in the finished panel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import get_web_settings
from app.sessions import (
    get_or_create_agent,
    get_session_info,
    record_exchange,
    reset_session,
)
from app.streaming import StreamingCallbackHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

# Wrapped around the searcher's draft before it goes to the redactor.
_REDACT_PROMPT = (
    "Rewrite the following draft answer about the CAE codebase into clean, "
    "concise Markdown per your system prompt. Keep every fact and every "
    "file/line citation. Output ONLY the Markdown.\n\n--- DRAFT ---\n"
)


class AskRequest(BaseModel):
    """Body of an /ai/ask-stream request.

    Attributes:
        question: The user's question.
        sessionId: Conversation session id, created client-side.
    """

    question: str
    sessionId: str


def _extract_usage(result: Any) -> dict[str, int]:
    """Pull token usage from a Strands agent result.

    Args:
        result: The object returned by invoking an agent.

    Returns:
        A dict with ``inputTokens`` and ``outputTokens`` (0 when unavailable).
    """
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None)
    if not usage:
        return {"inputTokens": 0, "outputTokens": 0}
    return {
        "inputTokens": int(usage.get("inputTokens", 0)),
        "outputTokens": int(usage.get("outputTokens", 0)),
    }


def _run_agent_streamed(
    agent: Any,
    prompt: str,
    stage: str,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[dict[str, Any]],
) -> tuple[str, dict[str, int]]:
    """Invoke one agent, streaming its events, and return its text and usage.

    Runs the (blocking) agent call on a worker thread and waits for it to
    finish, forwarding events tagged with ``stage`` as they arrive.

    Args:
        agent: The Strands agent to run.
        prompt: The prompt to send.
        stage: Stage tag added to every forwarded event.
        loop: The request event loop.
        queue: The SSE event queue.

    Returns:
        A tuple of the final text output and the token-usage dict.

    Raises:
        RuntimeError: When the agent invocation fails.
    """
    handler = StreamingCallbackHandler(queue, loop, stage)
    text: list[str] = [""]
    usage: list[dict[str, int]] = [{"inputTokens": 0, "outputTokens": 0}]
    error: list[str | None] = [None]
    done = threading.Event()

    def _run() -> None:
        try:
            result = agent(prompt, callback_handler=handler)
            text[0] = str(result)
            usage[0] = _extract_usage(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an error event
            error[0] = str(exc)
            logger.exception("stage=<%s> | agent invocation failed", stage)
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True).start()
    done.wait()

    if error[0] is not None:
        raise RuntimeError(error[0])
    return text[0], usage[0]


@router.post("/ask-stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """Stream the searcher's reasoning and the redactor's polished answer.

    Args:
        req: The question and session id.

    Returns:
        An SSE stream of stage-tagged events.

    Raises:
        HTTPException: On empty input, an exhausted session, or agent build
            failure.
    """
    question = (req.question or "").strip()
    session_id = (req.sessionId or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Missing 'question'.")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'sessionId'.")

    info = get_session_info(session_id)
    if info and info["remaining"] <= 0:
        raise HTTPException(
            status_code=429,
            detail="Session limit reached. Start a new conversation.",
        )

    try:
        searcher, session_info = get_or_create_agent(session_id, "searcher")
        redactor, _ = get_or_create_agent(session_id, "redactor")
    except Exception as exc:  # noqa: BLE001 - reported as a 503 to the client
        logger.exception("failed to build agents")
        raise HTTPException(status_code=503, detail=f"AI agents unavailable: {exc}") from exc

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    timeout = get_web_settings().invocation_timeout_seconds

    work_error: list[str | None] = [None]

    def _work() -> None:
        _run_both_agents(searcher, redactor, question, loop, queue, work_error)

    threading.Thread(target=_work, daemon=True).start()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    generator = _sse_generator(loop, queue, timeout, session_info, session_id, work_error)
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_both_agents(
    searcher: Any,
    redactor: Any,
    question: str,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[dict[str, Any]],
    work_error: list[str | None],
) -> None:
    """Run searcher then redactor, emitting stage and usage events.

    Args:
        searcher: The searcher agent.
        redactor: The redactor agent.
        question: The user's question.
        loop: The request event loop.
        queue: The SSE event queue.
        work_error: One-element list the error message is written into.
    """
    usage_total = {"inputTokens": 0, "outputTokens": 0}

    def emit(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def add_usage(usage: dict[str, int]) -> None:
        usage_total["inputTokens"] += usage.get("inputTokens", 0)
        usage_total["outputTokens"] += usage.get("outputTokens", 0)

    try:
        emit({"type": "stage_start", "stage": "searcher"})
        draft, draft_usage = _run_agent_streamed(searcher, question, "searcher", loop, queue)
        add_usage(draft_usage)
        emit({"type": "stage_complete", "stage": "searcher", "content": draft})

        emit({"type": "stage_start", "stage": "redactor"})
        final, final_usage = _run_agent_streamed(
            redactor, _REDACT_PROMPT + draft, "redactor", loop, queue
        )
        add_usage(final_usage)
        emit({"type": "stage_complete", "stage": "redactor", "content": final})
    except Exception as exc:  # noqa: BLE001 - surfaced as an error event
        work_error[0] = str(exc)
    finally:
        emit({"type": "usage", "usage": dict(usage_total)})
        emit({"type": "_done"})


def _sse_generator(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[dict[str, Any]],
    timeout: float,
    session_info: dict[str, Any],
    session_id: str,
    work_error: list[str | None],
) -> Iterator[str]:
    """Drain the event queue and yield SSE lines until the work is done.

    Args:
        loop: The request event loop the worker posts events to.
        queue: The SSE event queue.
        timeout: Per-event wait ceiling in seconds.
        session_info: The initial session payload to send first.
        session_id: The session id, for recording the completed exchange.
        work_error: Error slot the worker writes a failure message into.

    Yields:
        ``data: {...}`` SSE lines.
    """
    yield f"data: {json.dumps({'type': 'session', 'session': session_info})}\n\n"

    final_usage = {"inputTokens": 0, "outputTokens": 0}
    while True:
        future = asyncio.run_coroutine_threadsafe(queue.get(), loop)
        try:
            event = future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - timeout or loop error
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            return
        if event["type"] == "_done":
            break
        if event["type"] == "usage":
            final_usage = event["usage"]
            continue
        yield f"data: {json.dumps(event)}\n\n"

    if work_error[0]:
        yield f"data: {json.dumps({'type': 'error', 'error': work_error[0]})}\n\n"
        return

    updated = record_exchange(session_id)
    complete = {"type": "complete", "session": updated, "usage": final_usage}
    yield f"data: {json.dumps(complete)}\n\n"


class ResetRequest(BaseModel):
    """Body of an /ai/reset-session request.

    Attributes:
        sessionId: The session to reset.
    """

    sessionId: str


@router.post("/reset-session")
async def reset_session_endpoint(req: ResetRequest) -> JSONResponse:
    """Reset one conversation session.

    Args:
        req: The session id to reset.

    Returns:
        Whether a session was removed.
    """
    removed = reset_session((req.sessionId or "").strip())
    return JSONResponse({"success": True, "reset": removed})
