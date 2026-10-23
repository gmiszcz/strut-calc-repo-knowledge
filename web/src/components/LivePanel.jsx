import { useEffect, useRef } from "react";
import { useSelector } from "react-redux";
import MarkdownView from "./MarkdownView";
import "./LivePanel.css";

/**
 * Right panel: the searcher's live reasoning for the current turn — its
 * tool-call steps and the raw tokens as they stream over SSE.
 */
export default function LivePanel() {
  const turns = useSelector((s) => s.knowledge.turns);
  const streaming = useSelector((s) => s.knowledge.streaming);
  const stage = useSelector((s) => s.knowledge.stage);

  const current = turns[turns.length - 1] || null;
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [current?.live, current?.reasoning]);

  const reasoning = current?.reasoning || [];
  const live = current?.live || "";

  return (
    <section className="kb-live">
      <header className="kb-pane-head">
        <i className={`pi ${streaming && stage === "searcher" ? "pi-spin pi-cog" : "pi-bolt"}`} />
        <span>Live reasoning</span>
      </header>

      <div className="kb-live-scroll" ref={scrollRef}>
        {reasoning.length > 0 && (
          <ul className="kb-steps">
            {reasoning.map((step, i) => (
              <li key={i} className={step.status === "success" ? "is-done" : ""}>
                <i className={`pi ${step.icon}`} />
                <span>{step.text}</span>
              </li>
            ))}
          </ul>
        )}

        {live && <MarkdownView md={live} className="kb-live-text" />}

        {!reasoning.length && !live && (
          <p className="kb-live-empty">
            {streaming ? "Waiting for the first step…" : "The reasoning stream will appear here."}
          </p>
        )}
      </div>
    </section>
  );
}
