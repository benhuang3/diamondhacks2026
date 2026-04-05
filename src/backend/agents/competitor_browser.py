"""Competitor front-page snapshot runner built on the browser-use SDK.

Mirrors the structure of `browser_use_runner.py`: spins up a headless
Chromium via the browser-use Agent, asks Claude to observe (never click)
the competitor's front page, and returns a structured `CompetitorSnapshot`.

In DEMO_MODE (or on any failure — missing key, missing SDK, timeout,
exception) we return a deterministic demo snapshot based on a hash of
the URL so the downstream synthesis pipeline keeps working without keys
or network.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Optional

from src.config.settings import settings

from ..observability import scan_log
from .browser_use_runner import _MAX_CONCURRENT_AGENTS  # noqa: F401 — same budget as scan runner
from .browser_use_runner import _agent_semaphore
from .competitor_schemas import CompetitorSnapshot

log = logging.getLogger(__name__)

# Wall-clock cap on a single competitor-observation run.
_AGENT_WALL_CLOCK_SECONDS = 90.0

# Field-length caps applied to agent-returned content before it flows
# into downstream Claude prompts.
_MAX_TITLE_LEN = 200
_MAX_PRODUCT_LEN = 160
_MAX_SHIPPING_LEN = 200
_MAX_PROMO_LEN = 120
_MAX_NOTES_LEN = 500
_MAX_PROMOS_ITEMS = 5


def _clamp(s: Any, n: int) -> str:
    return str(s or "")[:n]


# --- Demo fallback --------------------------------------------------------

# Five rotating demo templates. We pick one via hash(url) so the same URL
# always resolves to the same snapshot (deterministic for tests + demos).
_DEMO_TEMPLATES: list[dict[str, Any]] = [
    {
        "title": "Demo Storefront — Everyday Essentials",
        "featured_product": "Everyday Canvas Tote",
        "featured_price": 24.99,
        "promos": ["SAVE10 — 10% off first order", "Spring Sale up to 25% off"],
        "shipping_note": "Free shipping on orders over $35",
        "notes": "Homepage emphasizes bundle deals and a loyalty program.",
    },
    {
        "title": "Demo Storefront — Premium Gear",
        "featured_product": "Pro Series Commuter Backpack",
        "featured_price": 89.00,
        "promos": ["WELCOME15 — 15% off new customers"],
        "shipping_note": "Free 2-day shipping on orders over $75",
        "notes": "Hero carousel highlights premium positioning and reviews.",
    },
    {
        "title": "Demo Storefront — Bargain Market",
        "featured_product": "Value Travel Pouch (3-pack)",
        "featured_price": 12.49,
        "promos": [
            "CLEARANCE — up to 50% off",
            "BUNDLE3 — buy 3, save $5",
            "FLASH24 — 24-hour flash sale",
        ],
        "shipping_note": "Flat $4.99 shipping, free over $25",
        "notes": "Aggressive price anchoring and strikethrough originals throughout.",
    },
    {
        "title": "Demo Storefront — Boutique",
        "featured_product": "Hand-Stitched Leather Wallet",
        "featured_price": 48.00,
        "promos": [],
        "shipping_note": "Free shipping on orders over $50",
        "notes": "Minimalist layout, editorial imagery, no visible promo codes.",
    },
    {
        "title": "Demo Storefront — Mega Retailer",
        "featured_product": "Core Crossbody Bag",
        "featured_price": 19.99,
        "promos": ["MEGA5 — $5 off $30", "Subscribe & save 10%"],
        "shipping_note": "Free shipping on orders over $25 (members: always free)",
        "notes": "Membership CTA above the fold, rotating category tiles.",
    },
]


def _demo_snapshot_for(url: str, *, is_fallback: bool = False) -> dict[str, Any]:
    """Deterministic demo snapshot keyed off the URL hash.

    ``is_fallback=True`` means we are returning demo data *from inside live
    mode* because the real agent run failed — callers (and downstream
    synthesis) should treat the numbers as placeholders, not observed.
    """
    h = hashlib.sha256((url or "").encode("utf-8")).digest()
    idx = h[0] % len(_DEMO_TEMPLATES)
    tpl = _DEMO_TEMPLATES[idx]
    return {
        "url": url,
        "title": tpl["title"],
        "featured_product": tpl["featured_product"],
        "featured_price": tpl["featured_price"],
        "promos": list(tpl["promos"]),
        "shipping_note": tpl["shipping_note"],
        "notes": tpl["notes"],
        "is_demo": True,
        "is_fallback": is_fallback,
    }


def _is_demo_key() -> bool:
    key = settings.anthropic_api_key or ""
    return (not key) or key.startswith("sk-ant-xxxxx") or key.lower() == "demo"


# --- Step callback --------------------------------------------------------

def _make_step_callback(scan_id: Optional[str], step_offset: int = 0):
    """Return a callback the Agent fires after each step that records the
    reasoning chain into scan_log for the given scan_id.

    ``step_offset`` is added to the agent's native 1-based step number so
    concurrent browses for different candidates write into distinct step
    ranges and don't collide in the UI.
    """
    if not scan_id:
        return None

    def _callback(_state, output, step_num: int) -> None:
        actions = []
        for a in getattr(output, "action", None) or []:
            dump = a.model_dump(exclude_unset=True) if hasattr(a, "model_dump") else {}
            for name in dump.keys():
                actions.append(name)
                break
        entry = {
            "step": int(step_num) + step_offset,
            "source": "browser-use",
            "evaluation": _clamp(getattr(output, "evaluation_previous_goal", "") or "", 300),
            "memory": _clamp(getattr(output, "memory", "") or "", 300),
            "next_goal": _clamp(getattr(output, "next_goal", "") or "", 300),
            "actions": actions[:3],
        }
        scan_log.append(scan_id, entry)

    return _callback


# --- browser-use Agent path -----------------------------------------------

async def _run_browser_use_agent(
    url: str,
    timeout_ms: int,
    *,
    scan_id: Optional[str] = None,
    step_offset: int = 0,
) -> dict[str, Any]:
    """Use browser-use's Agent to observe `url` and extract a CompetitorSnapshot.

    Raises on any failure so the caller can fall back. Caller is responsible
    for DEMO_MODE short-circuiting.
    """
    from browser_use import Agent, BrowserProfile  # type: ignore
    from browser_use.llm import ChatAnthropic  # type: ignore

    task = (
        f"Observe the front page of {url}. Do not click, do not add to "
        "cart, do not submit forms — only observe. Extract: the page "
        "title; the name of the single most prominent product being "
        "showcased (featured_product, e.g. 'Blue Leather Bifold Wallet'); "
        "its price (featured_price, USD float or null); any promotional "
        "codes or sale banners (promos list, <=5 items); the shipping "
        "policy if visible (shipping_note); short observations (notes). "
        "If no clear featured product exists, leave featured_product "
        "empty and featured_price null. Do not navigate or interact, "
        "only observe and return structured output."
    )

    llm = ChatAnthropic(
        model=settings.anthropic_model,  # type: ignore[arg-type]
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
        timeout=timeout_ms / 1000.0,
    )

    profile = BrowserProfile(headless=settings.browser_use_headless)

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=profile,
        output_model_schema=CompetitorSnapshot,
        use_vision=False,
        enable_planning=False,
        use_judge=False,
        use_thinking=False,
        max_actions_per_step=2,
        directly_open_url=True,
        register_new_step_callback=_make_step_callback(scan_id, step_offset),
    )

    history = await asyncio.wait_for(
        agent.run(max_steps=8),
        timeout=_AGENT_WALL_CLOCK_SECONDS,
    )
    parsed: Optional[CompetitorSnapshot] = history.get_structured_output(CompetitorSnapshot)
    if parsed is None:
        raise RuntimeError("browser-use agent returned no structured output")

    featured_price: Optional[float] = None
    if parsed.featured_price is not None:
        try:
            featured_price = max(0.0, float(parsed.featured_price))
        except (TypeError, ValueError):
            featured_price = None

    promos = [
        _clamp(p, _MAX_PROMO_LEN)
        for p in (parsed.promos or [])
        if str(p or "").strip()
    ][:_MAX_PROMOS_ITEMS]

    return {
        "url": url,
        "title": _clamp(parsed.title, _MAX_TITLE_LEN),
        "featured_product": _clamp(parsed.featured_product, _MAX_PRODUCT_LEN),
        "featured_price": featured_price,
        "promos": promos,
        "shipping_note": _clamp(parsed.shipping_note, _MAX_SHIPPING_LEN),
        "notes": _clamp(parsed.notes, _MAX_NOTES_LEN),
        "is_demo": False,
        "is_fallback": False,
    }


# --- Public entry point ---------------------------------------------------

async def extract_competitor_snapshot(
    url: str,
    *,
    scan_id: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    step_offset: int = 0,
) -> dict[str, Any]:
    """Return a dict snapshot of a competitor's front page.

    Never raises — always returns something usable. A deterministic demo
    snapshot is returned when there is no Anthropic key, when the
    browser-use SDK isn't present, when the agent times out, or when the
    agent fails. ``is_demo``/``is_fallback`` flags in the result tell the
    caller whether the numbers came from a real browse or from a template.
    """
    timeout_ms = timeout_ms or settings.browser_use_timeout_ms

    if settings.demo_mode or _is_demo_key():
        return _demo_snapshot_for(url, is_fallback=False)

    try:
        if scan_id:
            scan_log.append(
                scan_id,
                {
                    "step": step_offset,
                    "source": "browser-use",
                    "next_goal": f"observing competitor {url}…",
                },
            )
        async with _agent_semaphore:
            return await _run_browser_use_agent(
                url, timeout_ms, scan_id=scan_id, step_offset=step_offset,
            )
    except ImportError as e:
        log.warning("browser-use SDK unavailable, using demo snapshot: %s", e)
    except asyncio.TimeoutError:
        log.warning(
            "browser-use competitor agent exceeded %.0fs for %s, using demo snapshot",
            _AGENT_WALL_CLOCK_SECONDS, url,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("browser-use competitor agent failed for %s, using demo snapshot: %s", url, e)
    return _demo_snapshot_for(url, is_fallback=True)
