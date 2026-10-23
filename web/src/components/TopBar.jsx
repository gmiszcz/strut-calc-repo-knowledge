import { useDispatch, useSelector } from "react-redux";
import { InputText } from "primereact/inputtext";
import { Button } from "primereact/button";
import { setQuery, usageCost, resetGlobalUsage } from "@store";
import "./TopBar.css";

/** Format a token count compactly (e.g. 17381 -> "17.4k"). */
function fmtTokens(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/** Format a USD cost with enough precision for sub-cent values. */
function fmtCost(usd) {
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  if (usd >= 0.01) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(5)}`;
}

function UsageBadge({ label, usage, onReset }) {
  const cost = usageCost(usage);
  return (
    <div className="kb-usage">
      <span className="kb-usage-label">{label}</span>
      <span className="kb-usage-cost" title="Estimated cost (Claude Haiku 5.5)">
        {fmtCost(cost)}
      </span>
      <span className="kb-usage-tok" title="Input tokens">
        <i className="pi pi-arrow-down" /> {fmtTokens(usage.inputTokens)}
      </span>
      <span className="kb-usage-tok" title="Output tokens">
        <i className="pi pi-arrow-up" /> {fmtTokens(usage.outputTokens)}
      </span>
      {onReset && (
        <Button
          icon="pi pi-trash"
          text
          rounded
          severity="secondary"
          onClick={onReset}
          tooltip="Reset global totals"
          tooltipOptions={{ position: "bottom" }}
          className="kb-usage-reset"
        />
      )}
    </div>
  );
}

/** Top bar: search + ask + new session, with session and global cost badges. */
export default function TopBar({ onAsk, onNewSession }) {
  const dispatch = useDispatch();
  const query = useSelector((s) => s.knowledge.query);
  const streaming = useSelector((s) => s.knowledge.streaming);
  const sessionUsage = useSelector((s) => s.knowledge.sessionUsage);
  const globalUsage = useSelector((s) => s.knowledge.globalUsage);

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onAsk();
    }
  };

  return (
    <header className="kb-topbar">
      <div className="kb-topbar-search">
        <div className="kb-search-field">
          <i className="pi pi-search kb-search-icon" />
          <InputText
            value={query}
            onChange={(e) => dispatch(setQuery(e.target.value))}
            onKeyDown={onKeyDown}
            placeholder="Ask how the codebase works…"
            disabled={streaming}
            className="kb-search-input"
          />
        </div>
        <Button
          label={streaming ? "Working…" : "Ask"}
          icon={streaming ? "pi pi-spin pi-cog" : "pi pi-sparkles"}
          onClick={onAsk}
          disabled={streaming || !query.trim()}
        />
        <Button
          icon="pi pi-plus"
          severity="secondary"
          outlined
          onClick={onNewSession}
          disabled={streaming}
          tooltip="New conversation"
          tooltipOptions={{ position: "bottom" }}
        />
      </div>

      <div className="kb-topbar-usage">
        <UsageBadge label="Session" usage={sessionUsage} />
        <UsageBadge
          label="Global"
          usage={globalUsage}
          onReset={() => dispatch(resetGlobalUsage())}
        />
      </div>
    </header>
  );
}
