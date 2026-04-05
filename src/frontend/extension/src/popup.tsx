import * as React from "react";
import { createRoot } from "react-dom/client";
import type { ExtensionMessage, ScanStatus, PopupState } from "./types";

function sendMessage<T = unknown>(msg: ExtensionMessage): Promise<T> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (res) => resolve(res as T));
  });
}

function useActiveTabUrl() {
  const [url, setUrl] = React.useState<string>("");
  React.useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      setUrl(tabs[0]?.url ?? "");
    });
  }, []);
  return url;
}

function StatusPill({ status }: { status: ScanStatus["status"] | "idle" }) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    idle: { bg: "#f1f5f9", fg: "#334155", label: "idle" },
    pending: { bg: "#fef3c7", fg: "#92400e", label: "pending" },
    running: { bg: "#dbeafe", fg: "#1e40af", label: "running" },
    done: { bg: "#d1fae5", fg: "#065f46", label: "done" },
    failed: { bg: "#fee2e2", fg: "#991b1b", label: "failed" },
  };
  const s = map[status] ?? map.idle;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 9999,
        background: s.bg,
        color: s.fg,
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.03em",
      }}
    >
      {s.label}
    </span>
  );
}

function Popup() {
  const tabUrl = useActiveTabUrl();
  const [state, setState] = React.useState<PopupState>({
    scanId: null,
    status: null,
    lastError: null,
  });
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    sendMessage<PopupState>({ type: "GET_STATE" }).then((s) => {
      if (s) setState(s);
    });
    const listener = (msg: ExtensionMessage) => {
      if (msg.type === "SCAN_STATUS") {
        setState((prev) => ({ ...prev, status: msg.status }));
      }
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  async function onScan() {
    if (!tabUrl) return;
    setBusy(true);
    await sendMessage({ type: "START_SCAN", url: tabUrl });
    setBusy(false);
  }

  async function onClear() {
    await sendMessage({ type: "CLEAR_ANNOTATIONS" });
  }

  const status = state.status?.status ?? "idle";
  const progress = Math.round((state.status?.progress ?? 0) * 100);
  const findingsCount = state.status?.findings_count ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 6,
              background: "#4f46e5",
              color: "white",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            SR
          </div>
          <strong style={{ fontSize: 13 }}>Storefront Reviewer</strong>
        </div>
        <StatusPill status={status} />
      </div>

      <div
        style={{
          background: "#f8fafc",
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          padding: "8px 10px",
          fontSize: 11,
          color: "#475569",
          wordBreak: "break-all",
          lineHeight: 1.4,
        }}
      >
        {tabUrl || "No active tab"}
      </div>

      {status === "running" || status === "pending" ? (
        <div>
          <div
            style={{
              height: 6,
              background: "#f1f5f9",
              borderRadius: 9999,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${progress}%`,
                background: "#4f46e5",
                transition: "width 300ms ease",
              }}
            />
          </div>
          <p
            style={{
              margin: "6px 0 0 0",
              fontSize: 11,
              color: "#64748b",
            }}
          >
            {progress}% · polling every 3s
          </p>
        </div>
      ) : null}

      {status === "done" && (
        <div
          style={{
            fontSize: 12,
            color: "#065f46",
            background: "#ecfdf5",
            border: "1px solid #a7f3d0",
            borderRadius: 6,
            padding: "6px 10px",
          }}
        >
          {findingsCount} finding{findingsCount === 1 ? "" : "s"} injected into
          page.
        </div>
      )}

      {(status === "running" || status === "pending") && (
        <div
          style={{
            fontSize: 10,
            color: "#64748b",
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 6,
            padding: "6px 10px",
            lineHeight: 1.4,
          }}
        >
          Agent log streaming into the sidebar on the page.
        </div>
      )}

      {state.lastError && (
        <div
          style={{
            fontSize: 11,
            color: "#991b1b",
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: 6,
            padding: "6px 10px",
            wordBreak: "break-word",
          }}
        >
          {state.lastError}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={onScan}
          disabled={busy || !tabUrl}
          style={{
            flex: 1,
            height: 34,
            borderRadius: 6,
            border: "none",
            background: "#4f46e5",
            color: "white",
            fontWeight: 600,
            fontSize: 12,
            cursor: busy || !tabUrl ? "not-allowed" : "pointer",
            opacity: busy || !tabUrl ? 0.6 : 1,
          }}
        >
          {busy ? "Starting…" : "Scan this page"}
        </button>
        <button
          onClick={onClear}
          style={{
            height: 34,
            padding: "0 12px",
            borderRadius: 6,
            border: "1px solid #e2e8f0",
            background: "white",
            color: "#334155",
            fontWeight: 500,
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          Clear
        </button>
      </div>

      <p
        style={{
          margin: 0,
          fontSize: 10,
          color: "#94a3b8",
          textAlign: "center",
        }}
      >
        Backend: localhost:8000
      </p>
    </div>
  );
}


const container = document.getElementById("root");
if (container) createRoot(container).render(<Popup />);
