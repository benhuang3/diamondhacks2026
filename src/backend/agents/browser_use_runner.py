"""Lightweight browser runner.

For Phase 2 we keep this as a thin helper. In DEMO_MODE, `fetch_page_summary`
returns a canned snapshot. In live mode it attempts a Playwright fetch and
falls back to the demo snapshot on any failure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from src.config.settings import settings

log = logging.getLogger(__name__)


DEMO_SNAPSHOT = {
    "title": "Demo Storefront",
    "interactive_elements": [
        {"tag": "button", "selector": "button.checkout-btn", "text": "Checkout"},
        {"tag": "a", "selector": "a.nav-link", "text": "Shop"},
        {"tag": "input", "selector": "input#search", "text": ""},
        {"tag": "img", "selector": "img.hero", "text": ""},
        {"tag": "button", "selector": "button.add-to-cart", "text": "Add to cart"},
    ],
    "missing_alt_images": 3,
    "low_contrast_count": 2,
}


async def fetch_page_summary(url: str, *, timeout_ms: Optional[int] = None) -> dict[str, Any]:
    """Return a dict summary of interactive elements on the page.

    Never raises — always returns something usable. In DEMO_MODE or on any
    failure, returns a canned snapshot with the URL merged in.
    """
    timeout_ms = timeout_ms or settings.browser_use_timeout_ms
    snapshot = dict(DEMO_SNAPSHOT)
    snapshot["url"] = url

    # Demo short-circuit
    if (not settings.anthropic_api_key) or settings.anthropic_api_key.startswith("sk-ant-xxxxx"):
        return snapshot

    def _playwright_fetch() -> dict[str, Any] | None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:  # noqa: BLE001
            log.debug("playwright not available: %s", e)
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=settings.browser_use_headless)
                page = browser.new_page()
                page.goto(url, timeout=timeout_ms)
                title = page.title()
                # grab a small number of interactive elements
                elements = page.evaluate(
                    """
                    () => {
                      const sel = 'button, a[href], input, img';
                      const out = [];
                      document.querySelectorAll(sel).forEach((el, i) => {
                        if (i > 40) return;
                        out.push({
                          tag: el.tagName.toLowerCase(),
                          selector: el.id ? `#${el.id}` : el.className ? `${el.tagName.toLowerCase()}.${String(el.className).trim().split(/\\s+/)[0]}` : el.tagName.toLowerCase(),
                          text: (el.innerText || el.getAttribute('alt') || '').slice(0, 80),
                        });
                      });
                      return out;
                    }
                    """
                )
                missing_alt = page.evaluate(
                    "() => Array.from(document.images).filter(i => !i.alt).length"
                )
                browser.close()
                return {
                    "url": url,
                    "title": title,
                    "interactive_elements": elements or [],
                    "missing_alt_images": missing_alt or 0,
                    "low_contrast_count": 0,
                }
        except Exception as e:  # noqa: BLE001
            log.warning("Playwright fetch failed for %s: %s", url, e)
            return None

    result = await asyncio.to_thread(_playwright_fetch)
    return result or snapshot
