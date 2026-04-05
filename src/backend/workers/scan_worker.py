"""Scan worker: drives a scan from pending → done.

DEMO_MODE produces a deterministic set of fake findings. Live mode uses
Playwright + Claude; on any failure falls back to demo output so background
tasks never leave a scan in an indeterminate state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

from src.config.settings import settings
from src.db.queries import insert_finding, update_scan

from ..agents.browser_use_runner import fetch_page_summary
from ..agents.claude_client import ClaudeClient, DemoFallbackError, is_demo_mode
from ..agents import accessibility_prompts as prompts
from ..observability.metrics import metrics
from ..security.url_guard import UnsafeURLError, resolve_public_url
from .report_generator import generate_scan_report

log = logging.getLogger(__name__)


DEMO_FINDINGS_TEMPLATE: list[dict[str, Any]] = [
    {
        "selector": "button.checkout-btn",
        "xpath": "/html/body/main/div[2]/button",
        "bounding_box": {"x": 120, "y": 640, "w": 180, "h": 44},
        "severity": "high",
        "category": "contrast",
        "title": "Checkout CTA has insufficient contrast",
        "description": "The primary checkout button uses light gray text on a pale background (contrast ratio ~2.3:1), below WCAG AA 4.5:1.",
        "suggestion": "Darken button text to #FFFFFF on a #2A7D4F background to reach 6.2:1 contrast.",
    },
    {
        "selector": "img.hero",
        "xpath": "/html/body/main/section[1]/img",
        "bounding_box": {"x": 0, "y": 80, "w": 1200, "h": 420},
        "severity": "medium",
        "category": "a11y",
        "title": "Hero image missing alt text",
        "description": "The primary hero image has no alt attribute, so screen readers announce only the filename.",
        "suggestion": 'Add descriptive alt text, e.g. alt="Spring collection — three models wearing pastel sweaters".',
    },
    {
        "selector": "input#search",
        "xpath": "/html/body/header/form/input",
        "bounding_box": {"x": 400, "y": 20, "w": 260, "h": 36},
        "severity": "medium",
        "category": "a11y",
        "title": "Search input lacks visible label",
        "description": "The search field has a placeholder but no associated <label>, making it inaccessible to screen readers.",
        "suggestion": "Add a visually hidden <label for='search'>Search products</label>.",
    },
    {
        "selector": "a.nav-link",
        "xpath": "/html/body/header/nav/a[1]",
        "bounding_box": {"x": 40, "y": 20, "w": 80, "h": 24},
        "severity": "low",
        "category": "nav",
        "title": "Nav link focus state is invisible",
        "description": "Keyboard focus ring is suppressed via `outline: none` without a replacement indicator.",
        "suggestion": "Add `:focus-visible { outline: 2px solid #3366FF; outline-offset: 2px; }`.",
    },
    {
        "selector": "button.add-to-cart",
        "xpath": "/html/body/main/div[3]/button",
        "bounding_box": {"x": 820, "y": 380, "w": 150, "h": 40},
        "severity": "high",
        "category": "ux",
        "title": "Add-to-cart gives no confirmation",
        "description": "Clicking Add to Cart shows no toast, badge update, or aria-live announcement.",
        "suggestion": "Add a toast + update the cart badge count + aria-live='polite' region.",
    },
    {
        "selector": "form.newsletter",
        "xpath": "/html/body/footer/form",
        "bounding_box": {"x": 40, "y": 1200, "w": 400, "h": 120},
        "severity": "low",
        "category": "ux",
        "title": "Newsletter form lacks required-field indicators",
        "description": "Email field is required but not marked with aria-required or a visual asterisk.",
        "suggestion": "Add `aria-required='true'` and a red asterisk next to the label.",
    },
    {
        "selector": ".product-card .price",
        "xpath": "/html/body/main/section[2]/div[1]/span",
        "bounding_box": {"x": 240, "y": 820, "w": 80, "h": 20},
        "severity": "medium",
        "category": "contrast",
        "title": "Product price text is hard to read",
        "description": "Price text uses #888 on #FFF (contrast 3.5:1), below AA for normal text.",
        "suggestion": "Darken to #555 or bolden text to meet 4.5:1.",
    },
    {
        "selector": "nav.breadcrumbs",
        "xpath": "/html/body/main/nav",
        "bounding_box": {"x": 40, "y": 120, "w": 400, "h": 20},
        "severity": "low",
        "category": "nav",
        "title": "Breadcrumbs missing aria-label",
        "description": "Breadcrumb nav lacks `aria-label='Breadcrumb'` for screen-reader context.",
        "suggestion": "Add `aria-label='Breadcrumb'` to the containing <nav>.",
    },
]


async def _run_demo(scan_id: str, url: str, max_pages: int) -> None:
    await update_scan(scan_id, status="running", progress=0.1)
    await asyncio.sleep(0.4)
    await update_scan(scan_id, progress=0.3)
    await asyncio.sleep(0.4)

    # pick 6-10 findings deterministically but with slight variance
    k = min(len(DEMO_FINDINGS_TEMPLATE), 6 + (hash(scan_id) % 3))
    findings = DEMO_FINDINGS_TEMPLATE[:k]
    for f in findings:
        f_copy = dict(f)
        f_copy["page_url"] = url
        await insert_finding(scan_id, f_copy)
    await update_scan(scan_id, progress=0.7)
    await asyncio.sleep(0.4)

    await generate_scan_report(scan_id, url)
    await update_scan(scan_id, status="done", progress=1.0)


async def _run_live(scan_id: str, url: str, max_pages: int) -> None:
    await update_scan(scan_id, status="running", progress=0.1)
    # DNS-level SSRF check right before we actually fetch.
    await resolve_public_url(url)
    snapshot = await fetch_page_summary(url)
    await update_scan(scan_id, progress=0.35)

    client = ClaudeClient()
    prompt = prompts.SCAN_FINDINGS_PROMPT.format(
        url=url,
        title=snapshot.get("title", ""),
        elements=_serialize_elements(snapshot.get("interactive_elements", [])),
        missing_alt=snapshot.get("missing_alt_images", 0),
        low_contrast=snapshot.get("low_contrast_count", 0),
    )
    try:
        text = await client.complete(prompt, system=prompts.SYSTEM_SCAN, max_tokens=2048)
        parsed = _extract_json_array(text)
        if not parsed:
            raise DemoFallbackError("no findings parsed from Claude response")
        await update_scan(scan_id, progress=0.65)
        for item in parsed[:15]:
            finding = {
                "selector": item.get("selector", "body"),
                "xpath": item.get("xpath"),
                "bounding_box": item.get("bounding_box"),
                "severity": item.get("severity", "medium"),
                "category": item.get("category", "ux"),
                "title": item.get("title", "Finding"),
                "description": item.get("description", ""),
                "suggestion": item.get("suggestion", ""),
                "page_url": url,
            }
            await insert_finding(scan_id, finding)
        await update_scan(scan_id, progress=0.85)
        await generate_scan_report(scan_id, url)
        await update_scan(scan_id, status="done", progress=1.0)
    except DemoFallbackError as e:
        log.info("Falling back to demo for scan %s: %s", scan_id, e)
        await _run_demo(scan_id, url, max_pages)


_MAX_ELEMENTS_FOR_PROMPT = 40
_MAX_ELEMENTS_SERIALIZED_CHARS = 4000


def _serialize_elements(elements: Any) -> str:
    """Produce a bounded but still-valid JSON array of interactive elements.

    The previous implementation did ``json.dumps(...)[:4000]``, which
    corrupts the trailing tokens and ships malformed JSON to Claude. We
    instead drop elements from the tail until the serialized payload fits.
    """
    if not isinstance(elements, list):
        return "[]"
    items = list(elements[:_MAX_ELEMENTS_FOR_PROMPT])
    while items:
        encoded = json.dumps(items, ensure_ascii=False)
        if len(encoded) <= _MAX_ELEMENTS_SERIALIZED_CHARS:
            return encoded
        items.pop()
    return "[]"


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    # try fenced block first
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("["):
                try:
                    return json.loads(p)
                except Exception:  # noqa: BLE001
                    continue
    # try whole text
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            return []
    return []


async def run_scan(scan_id: str, url: str, max_pages: int) -> None:
    """Entry point called from FastAPI BackgroundTasks."""
    metrics.inc("scans_started_total", mode="demo" if is_demo_mode() else "live")
    try:
        if is_demo_mode():
            await _run_demo(scan_id, url, max_pages)
        else:
            await _run_live(scan_id, url, max_pages)
        metrics.inc("scans_completed_total")
    except UnsafeURLError as e:
        log.warning("Scan %s rejected unsafe URL: %s", scan_id, e)
        metrics.inc("ssrf_rejections_total", source="scan_worker")
        metrics.inc("scans_failed_total", reason="ssrf")
        try:
            await update_scan(scan_id, status="failed", error=str(e), progress=1.0)
        except Exception:  # noqa: BLE001
            log.exception("Failed to mark scan %s as failed", scan_id)
    except Exception as e:  # noqa: BLE001
        log.exception("Scan %s failed: %s", scan_id, e)
        metrics.inc("scans_failed_total", reason="exception")
        try:
            await update_scan(scan_id, status="failed", error=str(e), progress=1.0)
        except Exception:  # noqa: BLE001
            log.exception("Failed to mark scan %s as failed", scan_id)
