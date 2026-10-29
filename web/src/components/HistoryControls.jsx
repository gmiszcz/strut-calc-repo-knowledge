import { useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { Button } from "primereact/button";
import { Sidebar } from "primereact/sidebar";
import { Toast } from "primereact/toast";
import { ProgressBar } from "primereact/progressbar";
import { confirmDialog } from "primereact/confirmdialog";
import { listHistory, getHistory, saveHistory, deleteHistory } from "@api";
import { sessionSaved, sessionRestored, newSession, usageCost } from "@store";
import { fmtCost } from "@utils/format";
import "./HistoryControls.css";

/** Format a Unix timestamp (seconds) as a short local date and time. */
function fmtDate(seconds) {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/**
 * Save button plus a history sidebar listing saved conversations, where each
 * one can be restored or deleted. Only saved conversations are kept.
 */
export default function HistoryControls() {
  const dispatch = useDispatch();
  const sessionId = useSelector((s) => s.knowledge.sessionId);
  const turns = useSelector((s) => s.knowledge.turns);
  const sessionUsage = useSelector((s) => s.knowledge.sessionUsage);
  const streaming = useSelector((s) => s.knowledge.streaming);
  const savedTitle = useSelector((s) => s.knowledge.savedTitle);

  const toastRef = useRef(null);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);

  const showError = (summary, err) =>
    toastRef.current?.show({ severity: "error", summary, detail: err?.message || String(err) });

  const onSave = async () => {
    setSaving(true);
    try {
      const saved = await saveHistory({ sessionId, turns, sessionUsage });
      dispatch(sessionSaved(saved.title));
      toastRef.current?.show({ severity: "success", summary: "Conversation saved", detail: saved.title });
    } catch (err) {
      showError("Save failed", err);
    } finally {
      setSaving(false);
    }
  };

  const refresh = async () => {
    setLoading(true);
    try {
      setItems(await listHistory());
    } catch (err) {
      showError("Could not load history", err);
    } finally {
      setLoading(false);
    }
  };

  const onOpen = () => {
    setOpen(true);
    refresh();
  };

  const onRestore = async (id) => {
    try {
      dispatch(sessionRestored(await getHistory(id)));
      setOpen(false);
    } catch (err) {
      showError("Could not open conversation", err);
    }
  };

  const onDelete = (item) =>
    confirmDialog({
      header: "Delete conversation",
      message: `Delete "${item.title}"? This also removes the agent's memory of it and cannot be undone.`,
      icon: "pi pi-exclamation-triangle",
      acceptLabel: "Delete",
      rejectLabel: "Cancel",
      acceptClassName: "p-button-danger",
      defaultFocus: "reject",
      accept: async () => {
        try {
          await deleteHistory(item.id);
          setItems((prev) => prev.filter((i) => i.id !== item.id));
          if (item.id === sessionId) dispatch(newSession());
        } catch (err) {
          showError("Delete failed", err);
        }
      },
    });

  return (
    <>
      <Toast ref={toastRef} position="bottom-right" />
      <Button
        icon={savedTitle ? "pi pi-bookmark-fill" : "pi pi-bookmark"}
        severity="secondary"
        outlined={!savedTitle}
        onClick={onSave}
        loading={saving}
        disabled={streaming || turns.length === 0}
        tooltip={savedTitle ? `Saved as "${savedTitle}" (click to update)` : "Save conversation"}
        tooltipOptions={{ position: "bottom" }}
        aria-label="Save conversation"
      />
      <Button
        icon="pi pi-history"
        severity="secondary"
        outlined
        onClick={onOpen}
        disabled={streaming}
        tooltip="Saved conversations"
        tooltipOptions={{ position: "bottom" }}
        aria-label="Saved conversations"
      />

      <Sidebar
        visible={open}
        position="left"
        onHide={() => setOpen(false)}
        header="Saved conversations"
        className="kb-history"
      >
        {loading && <ProgressBar mode="indeterminate" style={{ height: 3 }} />}
        {!loading && items.length === 0 && (
          <p className="kb-history-empty">No saved conversations yet.</p>
        )}
        <ul className="kb-history-list">
          {items.map((item) => (
            <li
              key={item.id}
              className={`kb-history-item${item.id === sessionId ? " kb-history-item-active" : ""}`}
            >
              <button
                type="button"
                className="kb-history-open"
                onClick={() => onRestore(item.id)}
                title="Open this conversation"
              >
                <span className="kb-history-title">{item.title}</span>
                <small className="kb-history-meta">
                  {fmtDate(item.savedAt)} · {item.turnCount} {item.turnCount === 1 ? "question" : "questions"} ·{" "}
                  {fmtCost(usageCost(item.sessionUsage))}
                </small>
              </button>
              <Button
                icon="pi pi-trash"
                text
                rounded
                severity="danger"
                onClick={() => onDelete(item)}
                aria-label={`Delete ${item.title}`}
              />
            </li>
          ))}
        </ul>
      </Sidebar>
    </>
  );
}
