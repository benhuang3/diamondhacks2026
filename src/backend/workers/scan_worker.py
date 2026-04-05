"""Scan worker: drives a scan from pending → done.

DEMO_MODE produces a deterministic set of fake findings. Live mode uses
the browser-use agent + Claude; on any failure falls back to demo output
so background tasks never leave a scan in an indeterminate state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

from src.config.settings import settings
from src.db.queries import insert_findings_bulk, update_scan

from ..agents.claude_client import ClaudeClient, DemoFallbackError, is_demo_mode
from ..agents.page_crawler import crawl_storefront
from ..agents import accessibility_prompts as prompts
from ..observability import scan_log
from ..observability.metrics import metrics
from ..security.url_guard import (
    UnsafeURLError,
    resolve_public_url,
    validate_public_url,
)
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
    scan_log.append(scan_id, {"step": 0, "next_goal": "running in demo mode"})
    await asyncio.sleep(0.4)
    await update_scan(scan_id, progress=0.3)
    scan_log.append(scan_id, {"step": 1, "next_goal": "loading canned findings"})
    await asyncio.sleep(0.4)

    # pick 6-10 findings deterministically but with slight variance
    k = min(len(DEMO_FINDINGS_TEMPLATE), 6 + (hash(scan_id) % 3))
    batch = [dict(f, page_url=url) for f in DEMO_FINDINGS_TEMPLATE[:k]]
    await insert_findings_bulk(scan_id, batch)
    await update_scan(scan_id, progress=0.7)
    scan_log.append(
        scan_id, {"step": 2, "next_goal": f"inserted {k} findings"}
    )
    await asyncio.sleep(0.4)

    scan_log.append(scan_id, {"step": 3, "next_goal": "generating report"})
    await generate_scan_report(scan_id, url)
    await update_scan(scan_id, status="done", progress=1.0)
    scan_log.append(scan_id, {"step": 4, "next_goal": "done"})


async def _run_live(scan_id: str, url: str, max_pages: int) -> None:
    await update_scan(scan_id, status="running", progress=0.1)
    scan_log.append(scan_id, {"step": 0, "next_goal": f"validating {url}"})
    # DNS-level SSRF check right before we actually fetch.
    await resolve_public_url(url)

    await update_scan(scan_id, progress=0.2)
    scan_log.append(
        scan_id,
        {
            "step": 100,
            "source": "browser-use",
            "lane": "crawl",
            "next_goal": f"crawling up to {max_pages} pages from {url}",
        },
    )
    pages = await crawl_storefront(
        url, max_pages=max_pages, scan_id=scan_id, lane="crawl"
    )

    page_summary = ", ".join(
        f"{p.get('kind', 'other')}:{p.get('url', '')}" for p in pages[:8]
    )
    await update_scan(scan_id, progress=0.35)
    scan_log.append(
        scan_id,
        {
            "step": 101,
            "source": "browser-use",
            "lane": "crawl",
            "next_goal": f"crawl done: {len(pages)} page(s) visited",
            "evaluation": page_summary,
        },
    )

    # If every page is a fallback, still run Claude against just the home
    # page so the user gets *something* usable back.
    all_fallback = all(bool(p.get("is_fallback")) for p in pages)
    if all_fallback:
        # Keep only the first (home / input URL) page to run through Claude.
        pages_to_analyze = [pages[0]]
    else:
        pages_to_analyze = [p for p in pages if not p.get("is_fallback")]

    client = ClaudeClient()
    sem = asyncio.Semaphore(2)
    per_page_cap = 15
    global_cap = per_page_cap * max(1, len(pages_to_analyze))

    def _safe_page_url(raw: str) -> str:
        """Re-validate URLs the crawler returned before we stamp them on
        findings (they become sidebar navigation targets). browser-use's
        allowed_domains is the primary guard; this is belt-and-suspenders."""
        if not raw:
            return url
        try:
            return validate_public_url(raw)
        except UnsafeURLError as e:
            log.info(
                "Scan %s dropping crawler url %r: %s; using root",
                scan_id, raw, e,
            )
            return url

    async def _analyze_page(
        idx: int, page: dict[str, Any]
    ) -> list[dict[str, Any]]:
        page_url = _safe_page_url(page.get("url") or "")
        kind = page.get("kind", "other")
        title = page.get("title", "") or ""
        prompt_text = prompts.SCAN_FINDINGS_PROMPT_PER_PAGE.format(
            url=page_url,
            kind=kind,
            title=title,
            elements=_serialize_elements(page.get("interactive_elements", [])),
            missing_alt=page.get("missing_alt_images", 0),
            low_contrast=page.get("low_contrast_count", 0),
        )
        start_step = 200 + idx * 2
        done_step = start_step + 1
        async with sem:
            scan_log.append(
                scan_id,
                {
                    "step": start_step,
                    "source": "claude",
                    "lane": "claude",
                    "next_goal": f"analyzing {kind} page {page_url}",
                },
            )
            try:
                text = await client.complete(
                    prompt_text,
                    system=prompts.SYSTEM_SCAN,
                    max_tokens=2048,
                )
            except DemoFallbackError as e:
                log.info(
                    "Scan %s Claude call failed for %s: %s",
                    scan_id, page_url, e,
                )
                scan_log.append(
                    scan_id,
                    {
                        "step": done_step,
                        "lane": "claude",
                        "next_goal": f"findings on {page_url} (skipped)",
                        "evaluation": str(e)[:200],
                    },
                )
                return []
            parsed = _extract_json_array(text)
            items: list[dict[str, Any]] = []
            for item in (parsed or [])[:per_page_cap]:
                items.append(
                    {
                        "selector": item.get("selector", "body"),
                        "xpath": item.get("xpath"),
                        "bounding_box": item.get("bounding_box"),
                        "severity": item.get("severity", "medium"),
                        "category": item.get("category", "ux"),
                        "title": item.get("title", "Finding"),
                        "description": item.get("description", ""),
                        "suggestion": item.get("suggestion", ""),
                        "page_url": page_url,
                    }
                )
            scan_log.append(
                scan_id,
                {
                    "step": done_step,
                    "lane": "claude",
                    "next_goal": (
                        f"findings on {page_url} "
                        f"({len(items)} found)"
                    ),
                },
            )
            return items

    try:
        results = await asyncio.gather(
            *(
                _analyze_page(i, p)
                for i, p in enumerate(pages_to_analyze)
            )
        )
        all_findings: list[dict[str, Any]] = []
        for findings in results:
            all_findings.extend(findings)
            if len(all_findings) >= global_cap:
                break
        all_findings = all_findings[:global_cap]
        if not all_findings:
            raise DemoFallbackError("no findings parsed from Claude responses")
        await insert_findings_bulk(scan_id, all_findings)
        await update_scan(scan_id, progress=0.85)
        scan_log.append(
            scan_id,
            {
                "step": 102,
                "next_goal": (
                    f"persisted {len(all_findings)} findings "
                    f"across {len(pages_to_analyze)} page(s)"
                ),
            },
        )
        await generate_scan_report(scan_id, url)
        await update_scan(scan_id, status="done", progress=1.0)
        scan_log.append(scan_id, {"step": 103, "next_goal": "done"})
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
