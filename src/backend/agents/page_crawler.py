"""Multi-page storefront crawler built on browser-use Cloud.

Mirrors the structure of ``competitor_browser.extract_checkout_snapshot``
but for accessibility scanning: starts at the home URL, follows a handful
of product/category links (BFS depth 1), and finishes with a lightweight
add-to-cart + view-cart walk. The goal is coverage of the whole
storefront (home → category → product → cart) so the downstream scan
pipeline can reason about accessibility across the full purchase funnel,
not just the landing page.

Cloud-or-demo only: when ``settings.demo_mode`` is set, the Anthropic key
looks like a placeholder, the cloud isn't configured, or the cloud agent
throws for any reason, we return a deterministic demo snapshot. The
public ``crawl_storefront`` never raises and always returns at least one
PageVisit entry (the home URL) so the caller can render something.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from src.config.settings import settings

from ..observability import scan_log
from .browser_use_cloud import CloudAgentError, cloud_enabled, run_cloud_agent
from .page_crawler_schemas import CrawlSnapshot

log = logging.getLogger(__name__)

# Wall-clock cap per sub-agent (browse OR checkout). Two cloud tasks now
# run in parallel so each has its own shorter budget.
_BROWSE_WALL_CLOCK_SECONDS = 150.0
_CHECKOUT_WALL_CLOCK_SECONDS = 120.0

# Field-length caps applied to agent-returned content before it flows
# into downstream Claude prompts or the DB. Mirrors browser_use_runner.
_MAX_TITLE_LEN = 200
_MAX_SELECTOR_LEN = 200
_MAX_TEXT_LEN = 80
_MAX_TAG_LEN = 16
_MAX_URL_LEN = 2048
_MAX_ELEMENTS_PER_PAGE = 12

# Safety hard-cap on pages we will ever return — the public max_pages
# argument is clamped against this so a caller passing a huge number
# doesn't blow the cloud task budget.
_ABSOLUTE_MAX_PAGES = 8

# Step-offset bands in scan_log. competitor worker uses 500+, scan
# worker uses 0-10, 100-103, 200-215; browse = 300, checkout = 400.
_BROWSE_STEP_OFFSET = 300
_CHECKOUT_STEP_OFFSET = 400
# Minimum total max_pages budget required before we bother running the
# checkout-walk agent (cart pages cost ~2 slots: product + cart).
_CHECKOUT_MIN_BUDGET = 3

# Valid page-kind values. Anything else the agent returns is coerced to
# "other" so downstream code can trust the literal type.
_VALID_KINDS = {"home", "category", "product", "cart", "other"}


def _clamp(s: Any, n: int) -> str:
    return str(s or "")[:n]


def _is_demo_key() -> bool:
    """True when no real Anthropic key is configured (same rule as
    ``browser_use_runner._is_demo_key`` — copied, not imported, because
    that name is private to the other module)."""
    key = settings.anthropic_api_key or ""
    return (not key) or key.startswith("sk-ant-xxxxx") or key.lower() == "demo"


def _domain_allowlist(url: str) -> Optional[list[str]]:
    """Build an ``allowed_domains`` entry from a URL.

    Returns ``None`` if the host can't be determined. The ``*.`` wildcard
    lets the agent follow sibling subdomains (e.g. shop.example.com from
    www.example.com) while keeping it off third-party payment / auth
    pages. Leading ``www.`` is stripped. Mirrors competitor_browser."""
    try:
        host = urlparse(url).hostname
    except Exception:  # noqa: BLE001
        return None
    if not host:
        return None
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return [f"*.{host}", host]


async def _detect_platform(url: str) -> Optional[str]:
    """Detect the ecommerce platform for a URL by sniffing response
    headers + light body markers. Returns ``'shopify'`` or ``None``.

    Mirrors the pattern from competitor_browser. Kept as a local copy
    rather than an import because the competitor module owns its copy
    and we don't want cross-module private coupling."""
    import httpx  # local import — keeps startup cost off the hot path

    try:
        async with httpx.AsyncClient(
            timeout=5.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
            },
        ) as client:
            resp = await client.get(url)
    except Exception as e:  # noqa: BLE001
        log.debug("platform detection failed for %s: %s", url, e)
        return None

    headers_lc = {k.lower(): (v or "").lower() for k, v in resp.headers.items()}
    if "x-shopid" in headers_lc or "x-shopify-stage" in headers_lc:
        return "shopify"
    powered_by = (
        headers_lc.get("powered-by", "") + " " + headers_lc.get("x-powered-by", "")
    )
    if "shopify" in powered_by:
        return "shopify"
    if "shopify" in headers_lc.get("server", ""):
        return "shopify"
    body = (getattr(resp, "text", "") or "")[:4096].lower()
    if "cdn.shopify.com" in body or "shopify-section" in body:
        return "shopify"
    return None


def _skill_ids_for_platform(platform: Optional[str]) -> Optional[list[str]]:
    """Return a skill-ids list for the detected platform, or None."""
    if platform == "shopify" and settings.shopify_skill_id:
        return [settings.shopify_skill_id]
    return None


# --- Demo fallback --------------------------------------------------------

def _demo_crawl_for(url: str, max_pages: int) -> list[dict[str, Any]]:
    """Deterministic demo crawl snapshot — 3-4 pages with distinct kinds
    so the downstream renderer has something varied to show. Every entry
    is flagged ``is_fallback=True``."""
    base = (url or "").rstrip("/")
    pages: list[dict[str, Any]] = [
        {
            "url": base or "https://demo.example.com",
            "title": "Demo Storefront — Home",
            "kind": "home",
            "interactive_elements": [
                {"tag": "a", "selector": "a.nav-link[href='/shop']", "text": "Shop"},
                {"tag": "a", "selector": "a.nav-link[href='/sale']", "text": "Sale"},
                {"tag": "input", "selector": "input#search", "text": ""},
                {"tag": "button", "selector": "button.hero-cta", "text": "Shop now"},
                {"tag": "img", "selector": "img.hero", "text": ""},
            ],
            "missing_alt_images": 3,
            "low_contrast_count": 2,
            "is_fallback": True,
        },
        {
            "url": f"{base}/collections/all" if base else "https://demo.example.com/collections/all",
            "title": "Demo Storefront — Shop All",
            "kind": "category",
            "interactive_elements": [
                {"tag": "a", "selector": "a.product-card[data-id='1']", "text": "Everyday Tote"},
                {"tag": "a", "selector": "a.product-card[data-id='2']", "text": "Canvas Backpack"},
                {"tag": "button", "selector": "button.filter-toggle", "text": "Filter"},
                {"tag": "img", "selector": "img.product-thumb", "text": ""},
            ],
            "missing_alt_images": 4,
            "low_contrast_count": 1,
            "is_fallback": True,
        },
        {
            "url": f"{base}/products/everyday-tote" if base else "https://demo.example.com/products/everyday-tote",
            "title": "Everyday Canvas Tote — Demo Storefront",
            "kind": "product",
            "interactive_elements": [
                {"tag": "button", "selector": "button.add-to-cart", "text": "Add to cart"},
                {"tag": "button", "selector": "button.qty-plus", "text": "+"},
                {"tag": "button", "selector": "button.qty-minus", "text": "-"},
                {"tag": "img", "selector": "img.product-hero", "text": ""},
            ],
            "missing_alt_images": 2,
            "low_contrast_count": 3,
            "is_fallback": True,
        },
        {
            "url": f"{base}/cart" if base else "https://demo.example.com/cart",
            "title": "Your Cart — Demo Storefront",
            "kind": "cart",
            "interactive_elements": [
                {"tag": "button", "selector": "button.checkout-btn", "text": "Checkout"},
                {"tag": "a", "selector": "a.continue-shopping", "text": "Continue shopping"},
                {"tag": "input", "selector": "input[name='promo']", "text": ""},
            ],
            "missing_alt_images": 1,
            "low_contrast_count": 2,
            "is_fallback": True,
        },
    ]
    # Respect max_pages but always keep the home page.
    cap = max(1, min(int(max_pages or 1), len(pages)))
    return pages[:cap]


def _coerce_kind(kind: Any) -> str:
    k = str(kind or "other").strip().lower()
    return k if k in _VALID_KINDS else "other"


def _normalize_pages(parsed: CrawlSnapshot, *, cap: int) -> list[dict[str, Any]]:
    """Clamp field lengths and coerce types from a CrawlSnapshot into
    plain dicts matching the public contract."""
    out: list[dict[str, Any]] = []
    for page in (parsed.pages or [])[:cap]:
        elements: list[dict[str, Any]] = []
        for e in (page.interactive_elements or [])[:_MAX_ELEMENTS_PER_PAGE]:
            elements.append(
                {
                    "tag": _clamp(getattr(e, "tag", ""), _MAX_TAG_LEN),
                    "selector": _clamp(getattr(e, "selector", ""), _MAX_SELECTOR_LEN),
                    "text": _clamp(getattr(e, "text", ""), _MAX_TEXT_LEN),
                }
            )
        out.append(
            {
                "url": _clamp(page.url, _MAX_URL_LEN),
                "title": _clamp(page.title, _MAX_TITLE_LEN),
                "kind": _coerce_kind(page.kind),
                "interactive_elements": elements,
                "missing_alt_images": max(0, int(page.missing_alt_images or 0)),
                "low_contrast_count": max(0, int(page.low_contrast_count or 0)),
                "is_fallback": False,
            }
        )
    return out


# --- Public entry point ---------------------------------------------------

def _normalize_url_key(u: str) -> str:
    """Normalize a URL for dedup: origin + lowercased path with trailing
    slash removed + search. Hash dropped. Empty string on parse failure."""
    if not u:
        return ""
    try:
        p = urlparse(u)
        if not p.scheme or not p.netloc:
            return u.strip().lower()
        path = (p.path or "/").rstrip("/") or "/"
        return f"{p.scheme}://{p.netloc.lower()}{path}{('?' + p.query) if p.query else ''}"
    except Exception:  # noqa: BLE001
        return u.strip().lower()


def _merge_pages(
    browse_pages: list[dict[str, Any]],
    checkout_pages: list[dict[str, Any]],
    *,
    cap: int,
) -> list[dict[str, Any]]:
    """Dedupe by normalized URL, browse entries win when both agents hit
    the same URL (browse is recorded first and tends to have cleaner
    element listings since it didn't add-to-cart)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in list(browse_pages) + list(checkout_pages):
        key = _normalize_url_key(str(p.get("url") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= cap:
            break
    return out


async def _run_browse_agent(
    url: str,
    *,
    budget: int,
    scan_id: Optional[str],
    skill_ids: Optional[list[str]],
    allowed_domains: Optional[list[str]],
) -> list[dict[str, Any]]:
    """Shallow BFS agent: visits home + up to budget-1 category/product
    pages. Does NOT add-to-cart, does NOT navigate to the cart page."""
    task = (
        f"Starting at {url}: you are an accessibility observer walking a "
        "storefront. Record the HOME page first. Then, from the home nav "
        "and hero, pick 3-5 product or category links and visit up to "
        f"{max(1, budget - 1)} of them one at a time, recording each as "
        "a new page visit.\n"
        "Do NOT click 'Add to cart'. Do NOT navigate to the cart or "
        "checkout. Do NOT enter any form fields. Dismiss cookie banners "
        "and solve CAPTCHAs if they appear.\n"
        "For EACH page you visit, record:\n"
        "  • absolute URL (after any redirects),\n"
        "  • page title,\n"
        "  • 'kind' label — one of home / category / product / other,\n"
        "  • up to 12 interactive elements (button, a, input, img) with "
        "tag, precise CSS selector, and visible text or alt text "
        "(<=80 chars),\n"
        "  • count of <img> elements missing an alt attribute,\n"
        "  • rough count of low-contrast text/interactive elements.\n"
        f"Return a CrawlSnapshot with up to {budget} pages, home first."
    )
    parsed = await run_cloud_agent(
        task=task,
        schema=CrawlSnapshot,
        start_url=url,
        max_steps=12,
        scan_id=scan_id,
        step_offset=_BROWSE_STEP_OFFSET,
        timeout_s=_BROWSE_WALL_CLOCK_SECONDS,
        allowed_domains=allowed_domains,
        vision="auto",
        skill_ids=skill_ids,
        lane="browse",
    )
    return _normalize_pages(parsed, cap=budget)


async def _run_checkout_agent(
    url: str,
    *,
    scan_id: Optional[str],
    skill_ids: Optional[list[str]],
    allowed_domains: Optional[list[str]],
) -> list[dict[str, Any]]:
    """Checkout-walk agent: home → ONE product page → add-to-cart → cart
    page. Records product + cart pages (and optionally home). Forbidden
    from placing orders, entering payment info, or logging in."""
    task = (
        f"Starting at {url}: click ONE prominent product link from the "
        "home page. On the product page, click 'Add to cart'. Then "
        "navigate to the CART page. Record the PRODUCT page and the "
        "CART page.\n"
        "HARD RULES — do not break these:\n"
        "  • Do NOT proceed to checkout or click 'Checkout'.\n"
        "  • Do NOT enter ANY contact info, name, email, address, ZIP, "
        "or payment data.\n"
        "  • Do NOT create an account or log in.\n"
        "  • Do NOT place the order.\n"
        "  • If the product is out of stock, try one other product "
        "ONCE; if that also fails, return whatever pages you have.\n"
        "If you encounter a CAPTCHA, solve it. Dismiss cookie banners.\n"
        "For EACH page you visit, record:\n"
        "  • absolute URL (after any redirects),\n"
        "  • page title,\n"
        "  • 'kind' label — product / cart / other,\n"
        "  • up to 12 interactive elements (button, a, input, img) with "
        "tag, precise CSS selector, and visible text or alt text "
        "(<=80 chars),\n"
        "  • count of <img> elements missing an alt attribute,\n"
        "  • rough count of low-contrast text/interactive elements.\n"
        "Return a CrawlSnapshot with 2-3 pages (product then cart)."
    )
    parsed = await run_cloud_agent(
        task=task,
        schema=CrawlSnapshot,
        start_url=url,
        max_steps=10,
        scan_id=scan_id,
        step_offset=_CHECKOUT_STEP_OFFSET,
        timeout_s=_CHECKOUT_WALL_CLOCK_SECONDS,
        allowed_domains=allowed_domains,
        vision="auto",
        skill_ids=skill_ids,
        lane="checkout",
    )
    return _normalize_pages(parsed, cap=3)


async def crawl_storefront(
    url: str,
    *,
    max_pages: int,
    scan_id: Optional[str] = None,
    lane: str = "crawl",
) -> list[dict[str, Any]]:
    """Crawl a storefront with two parallel browser-use Cloud agents:

      * **browse**: shallow BFS from the home page → category/product
        pages (no cart, no add-to-cart).
      * **checkout**: home → one product → add-to-cart → cart page.

    Results are merged (deduped by normalized URL, browse wins on
    conflict) and capped at ``max_pages``. Never raises — falls back to
    a demo snapshot if both agents fail, and always returns at least one
    entry (the home URL).

    ``lane`` is accepted for API compatibility with earlier callers but
    the two sub-agents emit under their own ``browse`` / ``checkout``
    lanes so the UI can show them side-by-side.
    """
    _ = lane  # reserved — the sub-agents set their own lanes
    # Clamp max_pages defensively: callers may pass None, 0, or a huge
    # number. We always visit at least the home page, never more than
    # the module-level absolute cap.
    try:
        cap = int(max_pages)
    except Exception:  # noqa: BLE001
        cap = 1
    cap = max(1, min(cap, _ABSOLUTE_MAX_PAGES))

    # --- Demo short-circuit ---
    if settings.demo_mode or _is_demo_key() or not cloud_enabled():
        if scan_id:
            scan_log.append(
                scan_id,
                {
                    "step": _BROWSE_STEP_OFFSET,
                    "source": "worker",
                    "lane": "browse",
                    "next_goal": "crawler running in demo mode",
                    "evaluation": url,
                },
            )
        return _demo_crawl_for(url, cap)

    # --- Cloud-driven parallel walk: browse + checkout ---
    platform = await _detect_platform(url)
    skill_ids = _skill_ids_for_platform(platform)
    allowed_domains = _domain_allowlist(url)
    if scan_id and platform:
        scan_log.append(
            scan_id,
            {
                "step": _BROWSE_STEP_OFFSET,
                "source": "worker",
                "lane": "browse",
                "next_goal": (
                    f"detected platform={platform}"
                    + (" (skill playback enabled)" if skill_ids else "")
                ),
            },
        )

    # Budget split: browse gets max_pages - 2 (min 1), checkout covers
    # product + cart (~2 slots). For small caps we skip checkout and
    # give everything to browse.
    run_checkout = cap >= _CHECKOUT_MIN_BUDGET
    browse_budget = max(1, cap - 2) if run_checkout else cap

    if scan_id:
        scan_log.append(
            scan_id,
            {
                "step": _BROWSE_STEP_OFFSET,
                "source": "worker",
                "lane": "browse",
                "next_goal": (
                    f"launching browse agent (budget={browse_budget})"
                    + (
                        " + checkout agent"
                        if run_checkout
                        else " (checkout skipped — cap too small)"
                    )
                ),
                "evaluation": url,
            },
        )

    browse_coro = _run_browse_agent(
        url,
        budget=browse_budget,
        scan_id=scan_id,
        skill_ids=skill_ids,
        allowed_domains=allowed_domains,
    )
    coros: list[Any] = [browse_coro]
    if run_checkout:
        coros.append(
            _run_checkout_agent(
                url,
                scan_id=scan_id,
                skill_ids=skill_ids,
                allowed_domains=allowed_domains,
            )
        )

    results = await asyncio.gather(*coros, return_exceptions=True)

    def _unpack(res: Any, which: str) -> list[dict[str, Any]]:
        if isinstance(res, list):
            return res
        if isinstance(res, CloudAgentError):
            log.warning("%s agent failed for %s: %s", which, url, res)
        elif isinstance(res, BaseException):
            log.warning(
                "%s agent exception for %s: %s: %s",
                which, url, type(res).__name__, res,
            )
        return []

    browse_pages = _unpack(results[0], "browse")
    checkout_pages = _unpack(results[1], "checkout") if run_checkout else []

    merged = _merge_pages(browse_pages, checkout_pages, cap=cap)
    if not merged:
        log.warning(
            "both crawler agents returned 0 pages for %s, using demo", url
        )
        return _demo_crawl_for(url, cap)
    return merged
