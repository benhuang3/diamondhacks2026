// Service worker: talks to backend, polls status, forwards annotations to content script.
// To point at a deployed backend, change API_BASE_URL below.

import type {
  ExtensionMessage,
  ScanCreateResponse,
  ScanStatus,
  AnnotationsResponse,
  PopupState,
} from "./types";

const API_BASE_URL = "http://localhost:8000";
const POLL_INTERVAL_MS = 3000;

const state: PopupState = {
  scanId: null,
  status: null,
  lastError: null,
};

let pollTimer: ReturnType<typeof setTimeout> | null = null;
let activeTabId: number | null = null;

async function loadState() {
  const stored = await chrome.storage.local.get([
    "scanId",
    "status",
    "lastError",
  ]);
  state.scanId = stored.scanId ?? null;
  state.status = stored.status ?? null;
  state.lastError = stored.lastError ?? null;
}

async function saveState() {
  await chrome.storage.local.set({
    scanId: state.scanId,
    status: state.status,
    lastError: state.lastError,
  });
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

async function ensureContentScript(tabId: number): Promise<boolean> {
  // If the tab was opened before the extension loaded, the manifest
  // content script was never injected. Probe with PING first; on failure
  // inject the built script + CSS programmatically using the paths the
  // bundler wrote into the final manifest.
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: "PING",
    } satisfies ExtensionMessage);
    return true;
  } catch {
    // fall through and inject
  }
  const manifest = chrome.runtime.getManifest();
  const entry = manifest.content_scripts?.[0];
  if (!entry?.js) return false;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: entry.js,
    });
    if (entry.css?.length) {
      await chrome.scripting.insertCSS({
        target: { tabId },
        files: entry.css,
      });
    }
    return true;
  } catch (err) {
    console.warn("[storefront-reviewer] content-script inject failed", err);
    return false;
  }
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

async function pollOnce() {
  if (!state.scanId) return;
  try {
    const status = await apiGet<ScanStatus>(`/scan/${state.scanId}`);
    state.status = status;
    state.lastError = null;
    await saveState();
    broadcastState();

    if (status.status === "done") {
      stopPolling();
      await injectAnnotationsFromBackend();
      return;
    }
    if (status.status === "failed") {
      stopPolling();
      return;
    }
  } catch (err) {
    state.lastError = String(err);
    await saveState();
    broadcastState();
  }
  pollTimer = setTimeout(pollOnce, POLL_INTERVAL_MS);
}

async function injectAnnotationsFromBackend() {
  if (!state.scanId || activeTabId == null) return;
  try {
    const res = await apiGet<AnnotationsResponse>(
      `/annotations/${state.scanId}`,
    );
    const ok = await ensureContentScript(activeTabId);
    if (!ok) {
      throw new Error(
        "Could not inject annotation overlay into this tab. " +
          "Some pages (chrome://, web store, new tab) block extensions.",
      );
    }
    await chrome.tabs.sendMessage(activeTabId, {
      type: "INJECT_ANNOTATIONS",
      annotations: res.annotations,
    } satisfies ExtensionMessage);
  } catch (err) {
    state.lastError = String(err);
    await saveState();
    broadcastState();
  }
}

function broadcastState() {
  chrome.runtime
    .sendMessage({ type: "SCAN_STATUS", status: state.status })
    .catch(() => {
      // popup may be closed — ignore
    });
}

async function startScan(url: string) {
  stopPolling();
  state.lastError = null;
  state.status = null;
  await saveState();

  // remember the active tab so we can inject into it later
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  activeTabId = tab?.id ?? null;

  try {
    const res = await apiPost<ScanCreateResponse>("/scan", {
      url,
      max_pages: 5,
    });
    state.scanId = res.scan_id;
    state.status = {
      scan_id: res.scan_id,
      status: res.status,
      progress: 0,
      url,
      findings_count: 0,
    };
    await saveState();
    broadcastState();
    pollTimer = setTimeout(pollOnce, 500);
  } catch (err) {
    state.lastError = String(err);
    await saveState();
    broadcastState();
  }
}

async function clearAnnotations() {
  if (activeTabId == null) {
    const [tab] = await chrome.tabs.query({
      active: true,
      currentWindow: true,
    });
    activeTabId = tab?.id ?? null;
  }
  if (activeTabId != null) {
    const ok = await ensureContentScript(activeTabId);
    if (ok) {
      await chrome.tabs
        .sendMessage(activeTabId, {
          type: "CLEAR_ANNOTATIONS",
        } satisfies ExtensionMessage)
        .catch(() => {});
    }
  }
}

chrome.runtime.onMessage.addListener((msg: ExtensionMessage, _sender, send) => {
  (async () => {
    if (msg.type === "START_SCAN") {
      await startScan(msg.url);
      send({ ok: true });
    } else if (msg.type === "CLEAR_ANNOTATIONS") {
      await clearAnnotations();
      send({ ok: true });
    } else if (msg.type === "GET_STATE") {
      send(state);
    }
  })();
  return true; // async response
});

chrome.runtime.onStartup.addListener(loadState);
chrome.runtime.onInstalled.addListener(loadState);
loadState();
