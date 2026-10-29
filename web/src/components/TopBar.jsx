import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { InputText } from "primereact/inputtext";
import { Button } from "primereact/button";
import { Checkbox } from "primereact/checkbox";
import { OverlayPanel } from "primereact/overlaypanel";
import { ConfirmDialog, confirmDialog } from "primereact/confirmdialog";
import { setQuery, usageCost, resetGlobalUsage, setSetting } from "@store";
import { fmtCost } from "@utils/format";
import HistoryControls from "./HistoryControls";
import "./TopBar.css";

/** Format a token count compactly (e.g. 17381 -> "17.4k"). */
function fmtTokens(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}


/** True while the Ctrl key is held down anywhere in the window. */
function useCtrlHeld() {
  const [held, setHeld] = useState(false);
  useEffect(() => {
    const onKey = (e) => setHeld(e.ctrlKey);
    // Losing focus while Ctrl is down would otherwise leave it "stuck".
    const onBlur = () => setHeld(false);
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
      window.removeEventListener("blur", onBlur);
    };
  }, []);
  return held;
}

function UsageBadge({ label, usage, onReset, resetEnabled }) {
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
          disabled={!resetEnabled}
          tooltip={resetEnabled ? "Reset global totals" : "Hold Ctrl to reset global totals"}
          tooltipOptions={{ position: "bottom", showOnDisabled: true }}
          className="kb-usage-reset"
          aria-label="Reset global totals"
        />
      )}
    </div>
  );
}

const SETTING_OPTIONS = [
  {
    key: "shortAnswers",
    label: "Short answers",
    hint: "Brief summary, one consolidated answer across repos.",
  },
  {
    key: "detailedVerification",
    label: "Detailed verification",
    hint: "Verify every point across repos, then summarise in detail.",
  },
  {
    key: "consolidated",
    label: "Consolidated answer",
    hint: "One combined answer instead of a separate one per repo.",
  },
  {
    key: "perRepo",
    label: "Per-repository answer",
    hint: "Separate answer for each repo, then a consistency check between them.",
  },
];

/** Gear button with an overlay of answer-style checkboxes. */
function SettingsMenu({ disabled }) {
  const dispatch = useDispatch();
  const settings = useSelector((s) => s.knowledge.settings);
  const panelRef = useRef(null);
  const activeCount = Object.values(settings).filter(Boolean).length;

  return (
    <>
      <Button
        icon="pi pi-cog"
        severity="secondary"
        outlined={activeCount === 0}
        onClick={(e) => panelRef.current?.toggle(e)}
        disabled={disabled}
        tooltip="Answer settings"
        tooltipOptions={{ position: "bottom" }}
        aria-label="Answer settings"
        aria-haspopup="dialog"
      />
      <OverlayPanel ref={panelRef} className="kb-settings-panel">
        <div className="kb-settings">
          <span className="kb-settings-title">Answer settings</span>
          {SETTING_OPTIONS.map((opt) => {
            const id = `kb-setting-${opt.key}`;
            return (
              <div key={opt.key} className="kb-settings-row">
                <Checkbox
                  inputId={id}
                  checked={settings[opt.key]}
                  onChange={(e) => dispatch(setSetting({ key: opt.key, value: e.checked }))}
                />
                <label htmlFor={id} className="kb-settings-label">
                  <span>{opt.label}</span>
                  <small>{opt.hint}</small>
                </label>
              </div>
            );
          })}
        </div>
      </OverlayPanel>
    </>
  );
}

/** Top bar: search + ask + new session + settings, with session and global cost badges. */
export default function TopBar({ onAsk, onNewSession }) {
  const dispatch = useDispatch();
  const query = useSelector((s) => s.knowledge.query);
  const streaming = useSelector((s) => s.knowledge.streaming);
  const sessionUsage = useSelector((s) => s.knowledge.sessionUsage);
  const globalUsage = useSelector((s) => s.knowledge.globalUsage);
  const ctrlHeld = useCtrlHeld();

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onAsk();
    }
  };

  const onResetGlobal = () =>
    confirmDialog({
      header: "Reset global totals",
      message: "Are you sure you want to reset the global token and cost totals? This cannot be undone.",
      icon: "pi pi-exclamation-triangle",
      acceptLabel: "Reset",
      rejectLabel: "Cancel",
      acceptClassName: "p-button-danger",
      defaultFocus: "reject",
      accept: () => dispatch(resetGlobalUsage()),
    });

  return (
    <header className="kb-topbar">
      <ConfirmDialog />
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
        <SettingsMenu disabled={streaming} />
        <HistoryControls />
      </div>

      <div className="kb-topbar-usage">
        <UsageBadge label="Session" usage={sessionUsage} />
        <UsageBadge
          label="Global"
          usage={globalUsage}
          onReset={onResetGlobal}
          resetEnabled={ctrlHeld}
        />
      </div>
    </header>
  );
}
