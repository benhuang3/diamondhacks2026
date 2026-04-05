// Injected on every page. Receives annotations from background and overlays them on the DOM.

import type { ExtensionMessage, ScanFinding, ScanStatus, ScanStep } from "./types";

const OVERLAY_CLASS = "sr-highlight";
const TOOLTIP_CLASS = "sr-tooltip";
const SIDEBAR_ID = "sr-sidebar";
const FOCUS_CLASS = "sr-focus";

// Persisted across re-injects (e.g. auto-reinject after cross-page nav)
// so the user's collapse preference survives navigation.
let sidebarCollapsed = false;

// Live scan state streamed from the service worker so the sidebar can
// show the agent log + progress while a scan is running, before any
// findings exist. Null before first SIDEBAR_STATUS arrives.
let currentStatus: ScanStatus | null = null;
let currentAnnotations: ScanFinding[] = [];
let currentLocated: Set<string> = new Set();

function statusFingerprint(s: ScanStatus | null): string {
  if (!s) return "";
  const steps = s.steps || [];
  // Tail of step log: length + last step's step-number + ts capture
  // every meaningful mutation without walking the whole list.
  const last = steps[steps.length - 1];
  const lastKey = last
    ? `${last.step}:${last.ts ?? 0}:${(last.next_goal || "").slice(0, 24)}`
    : "";
  return `${s.status}|${Math.round((s.progress ?? 0) * 100)}|${s.findings_count}|${steps.length}|${lastKey}|${s.error ?? ""}`;
}
let lastRenderFingerprint = "";

function resolveElement(f: ScanFinding): HTMLElement | null {
  // 1. CSS selector
  try {
    const el = document.querySelector(f.selector);
    if (el instanceof HTMLElement) return el;
  } catch {
    // invalid selector — fall through
  }
  // 2. XPath
  if (f.xpath) {
    try {
      const result = document.evaluate(
        f.xpath,
        document,
        null,
        XPathResult.FIRST_ORDERED_NODE_TYPE,
        null,
      );
      const node = result.singleNodeValue;
      if (node instanceof HTMLElement) return node;
    } catch {
      // ignore
    }
  }
  return null;
}

function createOverlayForBox(
  f: ScanFinding,
  box: { x: number; y: number; w: number; h: number },
) {
  const overlay = document.createElement("div");
  overlay.className = `${OVERLAY_CLASS} sr-sev-${f.severity}`;
  overlay.dataset.srFindingId = f.id;
  overlay.style.position = "absolute";
  overlay.style.left = `${box.x + window.scrollX}px`;
  overlay.style.top = `${box.y + window.scrollY}px`;
  overlay.style.width = `${box.w}px`;
  overlay.style.height = `${box.h}px`;
  overlay.style.pointerEvents = "auto";
  overlay.style.zIndex = "2147483640";
  attachTooltip(overlay, f);
  document.body.appendChild(overlay);
}

function attachTooltip(host: HTMLElement, f: ScanFinding) {
  const tip = document.createElement("div");
  tip.className = `${TOOLTIP_CLASS} sr-sev-${f.severity}`;
  tip.innerHTML = `
    <div class="sr-tooltip-title"></div>
    <div class="sr-tooltip-desc"></div>
    <div class="sr-tooltip-sug"></div>
  `;
  (tip.querySelector(".sr-tooltip-title") as HTMLElement).textContent = f.title;
  (tip.querySelector(".sr-tooltip-desc") as HTMLElement).textContent =
    f.description;
  (tip.querySelector(".sr-tooltip-sug") as HTMLElement).textContent =
    "Fix: " + f.suggestion;
  host.appendChild(tip);
}

function overlayOnElement(f: ScanFinding, el: HTMLElement) {
  const rect = el.getBoundingClientRect();
  const wrapper = document.createElement("div");
  wrapper.className = `${OVERLAY_CLASS} sr-sev-${f.severity}`;
  wrapper.dataset.srFindingId = f.id;
  wrapper.style.position = "absolute";
  wrapper.style.left = `${rect.left + window.scrollX}px`;
  wrapper.style.top = `${rect.top + window.scrollY}px`;
  wrapper.style.width = `${rect.width}px`;
  wrapper.style.height = `${rect.height}px`;
  wrapper.style.pointerEvents = "auto";
  wrapper.style.zIndex = "2147483640";
  attachTooltip(wrapper, f);
  document.body.appendChild(wrapper);
}

function normalizeUrl(u: string): string {
  if (!u) return "";
  try {
    const parsed = new URL(u, location.href);
    const path = parsed.pathname.replace(/\/$/, "") || "/";
    return `${parsed.origin}${path}${parsed.search}`;
  } catch {
    return "";
  }
}

function isCurrentPage(pageUrl: string): boolean {
  const currentNorm = normalizeUrl(location.href);
  const pageNorm = normalizeUrl(pageUrl);
  if (!pageNorm) return false;
  if (currentNorm === pageNorm) return true;
  // If the current tab's URL has no pathname (root) and page_url is origin
  try {
    const curr = new URL(location.href);
    const page = new URL(pageUrl, location.href);
    if (
      (curr.pathname === "/" || curr.pathname === "") &&
      curr.search === "" &&
      page.origin === curr.origin &&
      (page.pathname === "/" || page.pathname === "") &&
      page.search === ""
    ) {
      return true;
    }
  } catch {
    // ignore
  }
  return false;
}

function clearOverlays() {
  document.querySelectorAll(`.${OVERLAY_CLASS}`).forEach((n) => n.remove());
}

const SIDEBAR_WIDTH_PX = 340;
// Narrow viewports can't afford to lose 340px — fall back to floating
// overlay mode (no page shrink) instead.
const NARROW_VIEWPORT_PX = 720;

function applySidebarPagePush() {
  const root = document.documentElement;
  root.classList.add("sr-sidebar-open");
  root.style.setProperty("--sr-sidebar-width", `${SIDEBAR_WIDTH_PX}px`);
  root.classList.toggle(
    "sr-sidebar-overlay",
    window.innerWidth < NARROW_VIEWPORT_PX,
  );
}

function releaseSidebarPagePush() {
  const root = document.documentElement;
  root.classList.remove("sr-sidebar-open");
  root.classList.remove("sr-sidebar-overlay");
  root.classList.remove("sr-sidebar-collapsed-push");
  root.style.removeProperty("--sr-sidebar-width");
}

// Keep overlay-mode decision fresh as the user resizes the window.
window.addEventListener("resize", () => {
  if (!document.documentElement.classList.contains("sr-sidebar-open")) return;
  document.documentElement.classList.toggle(
    "sr-sidebar-overlay",
    window.innerWidth < NARROW_VIEWPORT_PX,
  );
});

function injectAnnotations(annotations: ScanFinding[]) {
  clearOverlays();
  const located = new Set<string>();
  for (const f of annotations) {
    if (!isCurrentPage(f.page_url)) continue;
    const el = resolveElement(f);
    if (el) {
      overlayOnElement(f, el);
      located.add(f.id);
    } else if (f.bounding_box) {
      createOverlayForBox(f, f.bounding_box);
      located.add(f.id);
    }
  }
  currentAnnotations = annotations;
  currentLocated = located;
  renderUnifiedSidebar();
}

function clearAnnotations() {
  clearOverlays();
  const sidebar = document.getElementById(SIDEBAR_ID);
  if (sidebar) sidebar.remove();
  releaseSidebarPagePush();
  currentAnnotations = [];
  currentLocated = new Set();
  currentStatus = null;
  lastRenderFingerprint = "";
}

const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

const UNKNOWN_PAGE_KEY = "__unknown__";

interface PageGroup {
  key: string;
  pageUrl: string;
  label: string;
  findings: ScanFinding[];
  counts: { high: number; medium: number; low: number };
  isCurrent: boolean;
  isUnknown: boolean;
}

function pageLabel(pageUrl: string): string {
  try {
    const parsed = new URL(pageUrl, location.href);
    let path = parsed.pathname || "/";
    if (path.length > 1) path = path.replace(/\/$/, "");
    if (parsed.search) path += parsed.search;
    if (path.length > 40) path = path.slice(0, 39) + "…";
    return path || "/";
  } catch {
    return pageUrl.length > 40 ? pageUrl.slice(0, 39) + "…" : pageUrl;
  }
}

function buildPageGroups(annotations: ScanFinding[]): PageGroup[] {
  const groups = new Map<string, PageGroup>();
  for (const f of annotations) {
    const raw = f.page_url || "";
    const isUnknown = !raw;
    const key = isUnknown ? UNKNOWN_PAGE_KEY : normalizeUrl(raw) || raw;
    let g = groups.get(key);
    if (!g) {
      g = {
        key,
        pageUrl: raw,
        label: isUnknown ? "(unknown page)" : pageLabel(raw),
        findings: [],
        counts: { high: 0, medium: 0, low: 0 },
        isCurrent: !isUnknown && isCurrentPage(raw),
        isUnknown,
      };
      groups.set(key, g);
    }
    g.findings.push(f);
    if (f.severity === "high" || f.severity === "medium" || f.severity === "low") {
      g.counts[f.severity] += 1;
    }
  }
  // Sort findings in each group by severity
  for (const g of groups.values()) {
    g.findings.sort(
      (a, b) =>
        (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99),
    );
  }
  const arr = Array.from(groups.values());
  arr.sort((a, b) => {
    // unknown always last
    if (a.isUnknown && !b.isUnknown) return 1;
    if (!a.isUnknown && b.isUnknown) return -1;
    // current page first
    if (a.isCurrent && !b.isCurrent) return -1;
    if (!a.isCurrent && b.isCurrent) return 1;
    // then by total finding count desc
    return b.findings.length - a.findings.length;
  });
  return arr;
}

function createFindingItem(
  f: ScanFinding,
  located: Set<string>,
  isCrossPage: boolean,
): HTMLButtonElement {
  const item = document.createElement("button");
  item.type = "button";
  const hasLocation = !isCrossPage && located.has(f.id);
  const noLocation = !isCrossPage && !hasLocation;
  item.className = `sr-sidebar-item sr-sev-${f.severity}${noLocation ? " sr-no-location" : ""}${isCrossPage ? " sr-cross-page" : ""}`;
  item.dataset.srFindingId = f.id;
  if (noLocation) {
    item.disabled = true;
    item.title = "Element could not be located on this page";
  } else if (isCrossPage) {
    item.title = `Navigate to ${f.page_url}`;
  }
  const badge = document.createElement("span");
  badge.className = `sr-sidebar-badge sr-sev-${f.severity}`;
  badge.textContent = f.severity;
  const textWrap = document.createElement("div");
  textWrap.className = "sr-sidebar-item-text";
  const itemTitle = document.createElement("div");
  itemTitle.className = "sr-sidebar-item-title";
  itemTitle.textContent = f.title;
  const itemDesc = document.createElement("div");
  itemDesc.className = "sr-sidebar-item-desc";
  itemDesc.textContent = f.description;
  textWrap.appendChild(itemTitle);
  textWrap.appendChild(itemDesc);
  item.appendChild(badge);
  item.appendChild(textWrap);
  if (isCrossPage) {
    const arrow = document.createElement("span");
    arrow.className = "sr-cross-page-arrow";
    arrow.textContent = "↗";
    arrow.setAttribute("aria-hidden", "true");
    item.appendChild(arrow);
    item.addEventListener("click", () => {
      window.location.assign(f.page_url);
    });
  } else if (hasLocation) {
    item.addEventListener("click", () => focusFinding(f.id));
  }
  return item;
}

function renderPageGroup(
  group: PageGroup,
  located: Set<string>,
): HTMLDivElement {
  const wrap = document.createElement("div");
  wrap.className = "sr-page-group";
  const header = document.createElement("div");
  header.className = "sr-page-group-header";
  const label = document.createElement("div");
  label.className = "sr-page-group-label";
  label.textContent = group.label;
  label.title = group.isUnknown ? "(unknown page)" : group.pageUrl;
  header.appendChild(label);
  if (group.isCurrent) {
    const badge = document.createElement("span");
    badge.className = "sr-page-current-badge";
    badge.textContent = "current";
    header.appendChild(badge);
  }
  const counts = document.createElement("div");
  counts.className = "sr-page-group-counts";
  counts.innerHTML = `
    <span class="sr-chip sr-sev-high">${group.counts.high} high</span>
    <span class="sr-chip sr-sev-medium">${group.counts.medium} med</span>
    <span class="sr-chip sr-sev-low">${group.counts.low} low</span>
  `;
  wrap.appendChild(header);
  wrap.appendChild(counts);
  const isCrossPage = !group.isCurrent;
  for (const f of group.findings) {
    wrap.appendChild(createFindingItem(f, located, isCrossPage));
  }
  return wrap;
}

const STATUS_COPY: Record<string, { label: string; bg: string; fg: string }> = {
  pending: { label: "pending", bg: "#fef3c7", fg: "#92400e" },
  running: { label: "running", bg: "#dbeafe", fg: "#1e40af" },
  done: { label: "done", bg: "#d1fae5", fg: "#065f46" },
  failed: { label: "failed", bg: "#fee2e2", fg: "#991b1b" },
};

function sourceTone(source?: string): { border: string; chipBg: string; chipFg: string; label: string } {
  switch (source) {
    case "claude":
      return { border: "#a78bfa", chipBg: "#ede9fe", chipFg: "#6d28d9", label: "Claude" };
    case "browser-use":
      return { border: "#34d399", chipBg: "#d1fae5", chipFg: "#047857", label: "browser-use" };
    default:
      return { border: "#cbd5e1", chipBg: "#f1f5f9", chipFg: "#475569", label: "worker" };
  }
}

const AUTOSCROLL_THRESHOLD_PX = 24;

function captureFeedScrollState():
  | { top: number; atBottom: boolean }
  | null {
  const prev = document.querySelector<HTMLDivElement>(".sr-reasoning-feed");
  if (!prev) return null;
  const atBottom =
    prev.scrollHeight - prev.scrollTop - prev.clientHeight <=
    AUTOSCROLL_THRESHOLD_PX;
  return { top: prev.scrollTop, atBottom };
}

function renderReasoningPanel(
  steps: ScanStep[],
  scanActive: boolean,
  prevScroll: { top: number; atBottom: boolean } | null,
): HTMLDivElement {
  const wrap = document.createElement("div");
  wrap.className = "sr-reasoning";
  const headerRow = document.createElement("div");
  headerRow.className = "sr-reasoning-header";
  const label = document.createElement("div");
  label.className = "sr-reasoning-label";
  label.textContent = "Reasoning";
  headerRow.appendChild(label);
  // Surface the most recent live_url so the user can watch the cloud agent.
  let liveUrl: string | null = null;
  if (scanActive) {
    for (let i = steps.length - 1; i >= 0; i--) {
      const u = steps[i].live_url;
      if (u && (u.startsWith("https://") || u.startsWith("http://"))) {
        liveUrl = u;
        break;
      }
    }
  }
  if (liveUrl) {
    const a = document.createElement("a");
    a.className = "sr-live-link";
    a.href = liveUrl;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = "● Watch live ↗";
    headerRow.appendChild(a);
  }
  wrap.appendChild(headerRow);

  const feed = document.createElement("div");
  feed.className = "sr-reasoning-feed";
  for (const s of steps) {
    const tone = sourceTone(s.source);
    const row = document.createElement("div");
    row.className = "sr-reasoning-row";
    row.style.borderLeftColor = tone.border;
    const top = document.createElement("div");
    top.className = "sr-reasoning-top";
    const chip = document.createElement("span");
    chip.className = "sr-reasoning-chip";
    chip.style.background = tone.chipBg;
    chip.style.color = tone.chipFg;
    chip.textContent = s.lane || tone.label;
    const goal = document.createElement("span");
    goal.className = "sr-reasoning-goal";
    goal.textContent = s.next_goal || s.evaluation || "step";
    top.appendChild(chip);
    top.appendChild(goal);
    row.appendChild(top);
    if (s.actions && s.actions.length) {
      const actions = document.createElement("div");
      actions.className = "sr-reasoning-actions";
      actions.textContent = "→ " + s.actions.join(", ");
      row.appendChild(actions);
    }
    feed.appendChild(row);
  }
  // Scroll policy: if the user was already at the bottom (or this is
  // the first render), follow new entries. If they had scrolled up to
  // read history, preserve that scroll position across re-renders.
  queueMicrotask(() => {
    if (!prevScroll || prevScroll.atBottom) {
      feed.scrollTop = feed.scrollHeight;
    } else {
      feed.scrollTop = prevScroll.top;
    }
  });
  wrap.appendChild(feed);
  return wrap;
}

function renderUnifiedSidebar() {
  const hasStatus = currentStatus !== null;
  const hasFindings = currentAnnotations.length > 0;
  if (!hasStatus && !hasFindings) return;
  const prevScroll = captureFeedScrollState();
  const existing = document.getElementById(SIDEBAR_ID);
  if (existing) existing.remove();

  const status = currentStatus;
  const scanActive =
    !!status && (status.status === "pending" || status.status === "running");

  const sidebar = document.createElement("div");
  sidebar.id = SIDEBAR_ID;
  sidebar.className = "sr-sidebar";

  const header = document.createElement("div");
  header.className = "sr-sidebar-header";
  const title = document.createElement("div");
  title.className = "sr-sidebar-title";
  if (hasFindings) {
    title.textContent = `Storefront Reviewer · ${currentAnnotations.length} issue${currentAnnotations.length === 1 ? "" : "s"}`;
  } else if (status) {
    title.textContent = "Storefront Reviewer · scanning…";
  } else {
    title.textContent = "Storefront Reviewer";
  }
  const collapseBtn = document.createElement("button");
  collapseBtn.className = "sr-sidebar-collapse";
  collapseBtn.type = "button";
  collapseBtn.setAttribute("aria-label", "Collapse sidebar");
  if (sidebarCollapsed) sidebar.classList.add("sr-sidebar-collapsed");
  document.documentElement.classList.toggle(
    "sr-sidebar-collapsed-push",
    sidebarCollapsed,
  );
  collapseBtn.textContent = sidebarCollapsed ? "+" : "—";
  collapseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    sidebarCollapsed = !sidebar.classList.contains("sr-sidebar-collapsed");
    sidebar.classList.toggle("sr-sidebar-collapsed", sidebarCollapsed);
    document.documentElement.classList.toggle(
      "sr-sidebar-collapsed-push",
      sidebarCollapsed,
    );
    collapseBtn.textContent = sidebarCollapsed ? "+" : "—";
  });
  header.appendChild(title);
  header.appendChild(collapseBtn);
  sidebar.appendChild(header);

  // Status pill + progress bar (scanning) or summary chips (findings ready).
  if (status) {
    const meta = document.createElement("div");
    meta.className = "sr-sidebar-meta";
    const copy = STATUS_COPY[status.status] ?? STATUS_COPY.pending;
    const pill = document.createElement("span");
    pill.className = "sr-status-pill";
    pill.style.background = copy.bg;
    pill.style.color = copy.fg;
    pill.textContent = copy.label;
    meta.appendChild(pill);
    if (scanActive) {
      const progressWrap = document.createElement("div");
      progressWrap.className = "sr-progress";
      const bar = document.createElement("div");
      bar.className = "sr-progress-bar";
      const pct = Math.max(0, Math.min(100, Math.round((status.progress || 0) * 100)));
      bar.style.width = `${pct}%`;
      progressWrap.appendChild(bar);
      meta.appendChild(progressWrap);
      const pctLabel = document.createElement("span");
      pctLabel.className = "sr-progress-label";
      pctLabel.textContent = `${pct}%`;
      meta.appendChild(pctLabel);
    } else if (status.status === "failed" && status.error) {
      const err = document.createElement("div");
      err.className = "sr-sidebar-error";
      err.textContent = status.error.slice(0, 160);
      meta.appendChild(err);
    }
    sidebar.appendChild(meta);
  }

  // Reasoning feed — always present when we have steps.
  const steps = status?.steps || [];
  if (steps.length > 0) {
    sidebar.appendChild(renderReasoningPanel(steps, scanActive, prevScroll));
  }

  if (hasFindings) {
    const counts = { high: 0, medium: 0, low: 0 } as Record<string, number>;
    for (const f of currentAnnotations)
      counts[f.severity] = (counts[f.severity] ?? 0) + 1;
    const summary = document.createElement("div");
    summary.className = "sr-sidebar-summary";
    summary.innerHTML = `
      <span class="sr-chip sr-sev-high">${counts.high || 0} high</span>
      <span class="sr-chip sr-sev-medium">${counts.medium || 0} med</span>
      <span class="sr-chip sr-sev-low">${counts.low || 0} low</span>
    `;
    sidebar.appendChild(summary);

    const list = document.createElement("div");
    list.className = "sr-sidebar-list";
    const groups = buildPageGroups(currentAnnotations);
    if (groups.length <= 1) {
      const sorted = [...currentAnnotations].sort(
        (a, b) =>
          (SEVERITY_ORDER[a.severity] ?? 99) -
          (SEVERITY_ORDER[b.severity] ?? 99),
      );
      const onlyGroup = groups[0];
      const isCrossPage = !!onlyGroup && !onlyGroup.isCurrent && !onlyGroup.isUnknown;
      for (const f of sorted) {
        list.appendChild(createFindingItem(f, currentLocated, isCrossPage));
      }
    } else {
      for (const g of groups) {
        list.appendChild(renderPageGroup(g, currentLocated));
      }
    }
    sidebar.appendChild(list);
  }

  document.body.appendChild(sidebar);
  applySidebarPagePush();
}

function focusFinding(findingId: string) {
  document
    .querySelectorAll(`.${OVERLAY_CLASS}.${FOCUS_CLASS}`)
    .forEach((n) => n.classList.remove(FOCUS_CLASS));
  const overlay = document.querySelector(
    `.${OVERLAY_CLASS}[data-sr-finding-id="${CSS.escape(findingId)}"]`,
  ) as HTMLElement | null;
  if (!overlay) return;
  overlay.classList.add(FOCUS_CLASS);
  const rect = overlay.getBoundingClientRect();
  window.scrollTo({
    top: rect.top + window.scrollY - window.innerHeight / 3,
    behavior: "smooth",
  });
  document
    .querySelectorAll(".sr-sidebar-item.sr-active")
    .forEach((n) => n.classList.remove("sr-active"));
  const item = document.querySelector(
    `.sr-sidebar-item[data-sr-finding-id="${CSS.escape(findingId)}"]`,
  );
  if (item) item.classList.add("sr-active");
}

chrome.runtime.onMessage.addListener(
  (msg: ExtensionMessage, _sender, send) => {
    if (msg.type === "INJECT_ANNOTATIONS") {
      injectAnnotations(msg.annotations);
      send({ ok: true, injected: msg.annotations.length });
    } else if (msg.type === "SIDEBAR_STATUS") {
      currentStatus = msg.status;
      const fp = statusFingerprint(msg.status);
      if (fp !== lastRenderFingerprint) {
        lastRenderFingerprint = fp;
        renderUnifiedSidebar();
      }
      send({ ok: true });
    } else if (msg.type === "CLEAR_ANNOTATIONS") {
      clearAnnotations();
      sidebarCollapsed = false;
      send({ ok: true });
    } else if (msg.type === "PING") {
      send({ ok: true });
    }
    return true;
  },
);

// Website ↔ extension handshake stub: frontend can dispatch
// window.postMessage({source:"storefront-reviewer", type:"OPEN_SCAN", scan_id}).
window.addEventListener("message", (ev) => {
  const data = ev.data;
  if (
    data &&
    typeof data === "object" &&
    data.source === "storefront-reviewer"
  ) {
    // Forward to background for future integration.
    console.debug("[storefront-reviewer] received postMessage", data);
    chrome.runtime.sendMessage(data).catch(() => {});
  }
});
