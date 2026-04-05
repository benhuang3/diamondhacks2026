// Injected on every page. Receives annotations from background and overlays them on the DOM.

import type { ExtensionMessage, ScanFinding } from "./types";

const OVERLAY_CLASS = "sr-highlight";
const TOOLTIP_CLASS = "sr-tooltip";

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

function injectAnnotations(annotations: ScanFinding[]) {
  clearAnnotations();
  for (const f of annotations) {
    const el = resolveElement(f);
    if (el) {
      overlayOnElement(f, el);
    } else if (f.bounding_box) {
      createOverlayForBox(f, f.bounding_box);
    }
  }
}

function clearAnnotations() {
  document.querySelectorAll(`.${OVERLAY_CLASS}`).forEach((n) => n.remove());
}

chrome.runtime.onMessage.addListener(
  (msg: ExtensionMessage, _sender, send) => {
    if (msg.type === "INJECT_ANNOTATIONS") {
      injectAnnotations(msg.annotations);
      send({ ok: true, injected: msg.annotations.length });
    } else if (msg.type === "CLEAR_ANNOTATIONS") {
      clearAnnotations();
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
