// SSE client for the knowledge assistant backend.

/**
 * Stream an answer over SSE. Calls onEvent with each parsed event object and
 * returns a function that aborts the stream.
 *
 * Event types (each carries a `stage` of "searcher" | "redactor" where
 * relevant): session, stage_start, tool_start, tool_update, result_ready,
 * reasoning, text, stage_complete, complete, error.
 */
export function streamAsk({ question, sessionId, onEvent, onError }) {
  const ctrl = new AbortController();

  fetch("/api/ai/ask-stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, sessionId }),
    signal: ctrl.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        const txt = await res.text().catch(() => "");
        onError?.(new Error(txt || `HTTP ${res.status}`));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const chunk of parts) {
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;
            try {
              onEvent?.(JSON.parse(raw));
            } catch {
              // ignore malformed lines
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err?.name === "AbortError") return;
      onError?.(err);
    });

  return () => ctrl.abort();
}

/** Reset a conversation session on the backend. */
export async function resetSession(sessionId) {
  await fetch("/api/ai/reset-session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId }),
  });
}
