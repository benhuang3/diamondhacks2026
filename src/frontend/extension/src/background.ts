// Service worker: talks to backend, polls status, forwards annotations to content script.
// To point at a deployed backend, change API_BASE_URL below.

import type {
  ExtensionMessage,
  ScanCreateResponse,
  ScanFinding,
  ScanStatus,
  AnnotationsResponse,
  FixResponse,
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
// Last injected annotations, cached so we can re-inject when the scan
// tab navigates to another page covered by the scan (cross-page click).
let cachedAnnotations: ScanFinding[] = [];
// Timestamp of the most recent direct inject (post-scan or manual). The
// onUpdated listener uses this to suppress a duplicate reinject that
// fires when the same tab's load-complete event arrives shortly after.
let lastInjectAt = 0;
const REINJECT_COOLDOWN_MS = 2500;

async function loadState() {
  const stored = await chrome.storage.local.get([
    "scanId",
    "status",
    "lastError",
    "activeTabId",
    "cachedAnnotations",
  ]);
  state.scanId = stored.scanId ?? null;
  state.status = stored.status ?? null;
  state.lastError = stored.lastError ?? null;
  activeTabId = typeof stored.activeTabId === "number" ? stored.activeTabId : null;
  cachedAnnotations = Array.isArray(stored.cachedAnnotations)
    ? stored.cachedAnnotations
    : [];
}

async function saveState() {
  await chrome.storage.local.set({
    scanId: state.scanId,
    status: state.status,
    lastError: state.lastError,
    activeTabId,
    cachedAnnotations,
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
    cachedAnnotations = res.annotations;
    await saveState();
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
    lastInjectAt = Date.now();
  } catch (err) {
    state.lastError = String(err);
    await saveState();
    broadcastState();
  }
}

async function reinjectCachedAnnotations(tabId: number) {
  if (!cachedAnnotations.length) return;
  const ok = await ensureContentScript(tabId);
  if (!ok) return;
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: "INJECT_ANNOTATIONS",
      annotations: cachedAnnotations,
    } satisfies ExtensionMessage);
    lastInjectAt = Date.now();
  } catch {
    // tab may have navigated again / been closed — ignore
  }
}

// When the scan tab navigates (e.g. user clicks a cross-page finding in
// the sidebar and the page reloads), re-inject cached annotations so the
// sidebar and overlays come back — content.ts filters overlays to the
// new URL and lists the rest as cross-page items.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (tabId !== activeTabId) return;
  if (changeInfo.status !== "complete") return;
  if (!cachedAnnotations.length) return;
  // Skip if we just injected moments ago — the load-complete event that
  // fires right after the post-scan inject would otherwise cause a
  // redundant second inject on the same URL.
  if (Date.now() - lastInjectAt < REINJECT_COOLDOWN_MS) return;
  void reinjectCachedAnnotations(tabId);
});

function broadcastState() {
  chrome.runtime
    .sendMessage({ type: "SCAN_STATUS", status: state.status })
    .catch(() => {
      // popup may be closed — ignore
    });
  void broadcastSidebarStatus();
}

async function broadcastSidebarStatus() {
  if (activeTabId == null || !state.status) return;
  const msg: ExtensionMessage = {
    type: "SIDEBAR_STATUS",
    status: state.status,
  };
  try {
    await chrome.tabs.sendMessage(activeTabId, msg);
    return;
  } catch {
    // content script not yet injected — fall through to ensureContentScript
  }
  const ok = await ensureContentScript(activeTabId);
  if (!ok) return;
  try {
    await chrome.tabs.sendMessage(activeTabId, msg);
  } catch {
    // tab may have been closed — ignore
  }
}

async function startScan(url: string) {
  stopPolling();
  state.lastError = null;
  state.status = null;
  cachedAnnotations = [];
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
  cachedAnnotations = [];
  await saveState();
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

async function handleFixFinding(findingId: string) {
  const scanId = state.scanId;
  if (!scanId || activeTabId == null) return;
  try {
    const res = await fetch(
      `${API_BASE_URL}/scan/${encodeURIComponent(scanId)}/findings/${encodeURIComponent(findingId)}/fix`,
      { method: "POST", headers: { "Content-Type": "application/json" } },
    );
    if (!res.ok) {
      const body = await res.text();
      await chrome.tabs
        .sendMessage(activeTabId, {
          type: "FIX_ERROR",
          finding_id: findingId,
          error: `HTTP ${res.status}: ${body.slice(0, 200)}`,
        } satisfies ExtensionMessage)
        .catch(() => {});
      return;
    }
    const data = (await res.json()) as FixResponse;
    await chrome.tabs
      .sendMessage(activeTabId, {
        type: "APPLY_FIX",
        finding_id: data.finding_id,
        operation: data.operation,
      } satisfies ExtensionMessage)
      .catch(() => {});
  } catch (err) {
    try {
      await chrome.tabs.sendMessage(activeTabId, {
        type: "FIX_ERROR",
        finding_id: findingId,
        error: String(err).slice(0, 200),
      } satisfies ExtensionMessage);
    } catch {
      // tab closed — ignore
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
    } else if (msg.type === "FIX_FINDING") {
      // Don't block the reply — content script expects this to
      // return quickly and will wait for APPLY_FIX / FIX_ERROR.
      void handleFixFinding(msg.finding_id);
      send({ ok: true });
    }
  })();
  return true; // async response
});

chrome.runtime.onStartup.addListener(loadState);
chrome.runtime.onInstalled.addListener(loadState);
loadState();
