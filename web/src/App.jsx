import { useEffect, useRef } from "react";
import { useDispatch, useSelector } from "react-redux";
import { streamAsk, resetSession } from "@api";
import {
  askStarted,
  stageStarted,
  toolStart,
  toolUpdate,
  toolResult,
  reasoningToken,
  token,
  stageComplete,
  usageReported,
  askComplete,
  askFailed,
  newSession,
} from "@store";
import { buildPrompt } from "@utils/promptHints";
import TopBar from "@components/TopBar";
import ChatPanel from "@components/ChatPanel";
import LivePanel from "@components/LivePanel";
import "./App.css";

export default function App() {
  const dispatch = useDispatch();
  const query = useSelector((s) => s.knowledge.query);
  const sessionId = useSelector((s) => s.knowledge.sessionId);
  const streaming = useSelector((s) => s.knowledge.streaming);
  const settings = useSelector((s) => s.knowledge.settings);
  const abortRef = useRef(null);

  useEffect(() => () => abortRef.current?.(), []);

  const onAsk = () => {
    const q = query.trim();
    if (!q || streaming) return;
    dispatch(askStarted(q));

    abortRef.current = streamAsk({
      question: buildPrompt(q, settings),
      sessionId,
      onEvent: (event) => {
        switch (event.type) {
          case "stage_start":
            dispatch(stageStarted(event.stage));
            break;
          case "tool_start":
            dispatch(toolStart({ icon: event.icon, text: event.text }));
            break;
          case "tool_update":
            dispatch(toolUpdate({ icon: event.icon, text: event.text }));
            break;
          case "result_ready":
            dispatch(toolResult());
            break;
          case "reasoning":
            dispatch(reasoningToken(event.text));
            break;
          case "text":
            dispatch(token({ stage: event.stage, text: event.text }));
            break;
          case "stage_complete":
            dispatch(stageComplete({ stage: event.stage, content: event.content }));
            break;
          case "complete":
            if (event.usage) dispatch(usageReported(event.usage));
            dispatch(askComplete());
            break;
          case "error":
            dispatch(askFailed(event.error || "AI error"));
            break;
          default:
            break;
        }
      },
      onError: (err) => dispatch(askFailed(err?.message || "Failed to reach the assistant.")),
    });
  };

  const onNewSession = async () => {
    abortRef.current?.();
    try {
      await resetSession(sessionId);
    } catch {
      // Best-effort; a fresh client-side session id is enough.
    }
    dispatch(newSession());
  };

  return (
    <div className="kb-app">
      <TopBar onAsk={onAsk} onNewSession={onNewSession} />
      <main className="kb-main">
        <ChatPanel />
        <LivePanel />
      </main>
    </div>
  );
}
