import { useEffect, useRef } from "react";
import { useSelector } from "react-redux";
import { ProgressBar } from "primereact/progressbar";
import { Message } from "primereact/message";
import MarkdownView from "./MarkdownView";
import "./ChatPanel.css";

/**
 * Left panel: the conversation. User questions are right-aligned (like a
 * chat app), assistant answers (the redactor's Markdown) are left-aligned.
 * Scrolls, newest at the bottom.
 */
export default function ChatPanel() {
  const turns = useSelector((s) => s.knowledge.turns);
  const streaming = useSelector((s) => s.knowledge.streaming);
  const stage = useSelector((s) => s.knowledge.stage);
  const error = useSelector((s) => s.knowledge.error);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, streaming]);

  return (
    <section className="kb-chat">
      <header className="kb-pane-head">
        <i className="pi pi-comments" />
        <span>Conversation</span>
      </header>

      <div className="kb-chat-scroll">
        {turns.length === 0 && (
          <p className="kb-chat-empty">Ask a question to get started.</p>
        )}

        {turns.map((turn) => (
          <div key={turn.id} className="kb-turn">
            <div className="kb-msg kb-msg-user">
              <div className="kb-bubble kb-bubble-user">{turn.question}</div>
            </div>

            <div className="kb-msg kb-msg-assistant">
              <div className="kb-bubble kb-bubble-assistant">
                {turn.answer ? (
                  <MarkdownView md={turn.answer} />
                ) : turn.streaming ? (
                  <div className="kb-thinking">
                    <span>{stage === "redactor" ? "Writing the answer…" : "Searching the codebase…"}</span>
                    <ProgressBar mode="indeterminate" style={{ height: 3 }} />
                  </div>
                ) : (
                  <span className="kb-chat-empty">No answer.</span>
                )}
              </div>
            </div>
          </div>
        ))}

        {error && <Message severity="error" text={error} className="kb-chat-error" />}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}
