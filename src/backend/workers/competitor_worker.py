"""Competitor worker: 5-stage live pipeline.

  0. Target browse — observe the user's own store via browser-use.
  1. Discover — 4 parallel browser-use agents (or Claude fallback).
  1.5. Shared products — Claude names the top-3 product types the target
       + competitors all likely carry; top-1 becomes the cart-walk hint.
  2. Browse — browser-use adds a product to cart and extracts the
     breakdown for each competitor, bounded concurrency + early-exit.
  3. Synthesize — Claude writes a strategy brief + recommendations.

DEMO_MODE produces canned competitors and a basic synthesis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from src.config.settings import settings
from src.db.queries import insert_competitor_result, update_competitor_job

from ..agents.claude_client import ClaudeClient, DemoFallbackError, is_demo_mode
from ..agents.browser_use_cloud import cloud_enabled
from ..agents.competitor_browser import (
    discover_competitors_parallel,
    extract_checkout_snapshot,
    extract_competitor_snapshot,
)
from ..agents import competitor_prompts as prompts
from ..observability import cancellation, scan_log
from ..observability.cancellation import CancelledByUser
from ..observability.metrics import metrics
from ..security.url_guard import UnsafeURLError, validate_public_url
from .report_generator import generate_competitor_report

log = logging.getLogger(__name__)


DEMO_COMPETITORS: list[dict[str, Any]] = [
    {
        "name": "FreshMarket Co",
        "url": "https://freshmarket.example.com/product/1",
        "price": 29.99,
        "shipping": 4.99,
        "tax": 2.40,
        "discount": "SAVE10",
        "checkout_total": 34.38,
        "notes": "Free shipping over $35. 10% off with newsletter signup.",
    },
    {
        "name": "UrbanGoods",
        "url": "https://urbangoods.example.com/item/abc",
        "price": 32.50,
        "shipping": 6.99,
        "tax": 2.60,
        "discount": None,
        "checkout_total": 42.09,
        "notes": "No active promos. Ships from west coast warehouse.",
    },
    {
        "name": "ValuePick",
        "url": "https://valuepick.example.com/p/xyz",
        "price": 27.49,
        "shipping": 0.00,
        "tax": 2.20,
        "discount": "FREESHIP",
        "checkout_total": 29.69,
        "notes": "Free shipping promo auto-applied. Lowest price in set.",
    },
    {
        "name": "PrimeStore",
        "url": "https://primestore.example.com/dp/123",
        "price": 31.00,
        "shipping": 0.00,
        "tax": 2.48,
        "discount": None,
        "checkout_total": 33.48,
        "notes": "Prime 2-day shipping included.",
    },
    {
        "name": "BoutiqueHaus",
        "url": "https://boutiquehaus.example.com/shop/item",
        "price": 35.00,
        "shipping": 5.50,
        "tax": 2.80,
        "discount": "WELCOME15",
        "checkout_total": 37.05,
        "notes": "Premium brand positioning; 15% off first order.",
    },
]


_BROWSE_CONCURRENCY = 4
# Max browse attempts per competitor site. Each attempt goes through
# browser-use, so we keep this tight. On the second failure we drop the
# site and move to the next candidate from the discovery list.
_MAX_BROWSE_ATTEMPTS = 2
# Claude generates a long ranked list of competitors; browser-use works
# through it until max_competitors successful scrapes have landed.
# Remaining candidates are cancelled once we have enough successes.
_DISCOVERY_SPARES = 6

# Domains known to be captcha-walled, auth-gated, or otherwise to waste
# browse budget every time. These are frequently proposed by Claude's
# discovery step despite prompt instructions, so we enforce rejection
# deterministically after discovery. Matches registered domain OR any
# subdomain (e.g. "shop.amazon.com" matches "amazon.com").
_CAPTCHA_WALLED_DOMAINS: frozenset[str] = frozenset([
    # Mega-retailers & marketplaces
    "amazon.com", "amazon.co.uk", "amazon.ca", "walmart.com",
    "target.com", "bestbuy.com", "ebay.com", "etsy.com", "macys.com",
    "nordstrom.com", "nordstromrack.com", "dillards.com", "kohls.com",
    "jcpenney.com", "sears.com", "homedepot.com", "lowes.com",
    "costco.com", "samsclub.com", "bjs.com", "wayfair.com",
    "overstock.com", "alibaba.com", "aliexpress.com", "temu.com",
    "shein.com", "tjmaxx.com", "marshalls.com", "hsn.com", "qvc.com",
    # Athletic / shoe retailers with aggressive bot detection
    "finishline.com", "footlocker.com", "footaction.com",
    "dickssportinggoods.com", "dsw.com", "famousfootwear.com",
    "hibbett.com", "academy.com", "champssports.com", "eastbay.com",
    # Big athletic brands (direct sites are captcha-walled)
    "nike.com", "adidas.com", "newbalance.com", "underarmour.com",
    "puma.com", "reebok.com", "asics.com", "brooksrunning.com",
    "saucony.com", "converse.com", "vans.com",
    # Google / review aggregators (not storefronts)
    "google.com", "bing.com", "yelp.com", "trustpilot.com",
    "reddit.com", "wirecutter.com", "nytimes.com",
])


def _registered_domain(url: str) -> str:
    """Lowercase host with leading 'www.' stripped. Returns '' on failure."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_denylisted(url: str) -> bool:
    host = _registered_domain(url)
    if not host:
        return False
    for denied in _CAPTCHA_WALLED_DOMAINS:
        if host == denied or host.endswith("." + denied):
            return True
    return False


async def _filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    job_id: str,
    timeout_s: float = 3.0,
) -> list[dict[str, Any]]:
    """Drop candidates that are (a) on the captcha/auth-wall denylist or
    (b) unreachable via a cheap HEAD probe. ~3s per candidate in parallel;
    saves a full browser-use session start (~90s each) for dead domains.
    """
    # Pass 1: denylist (sync, free).
    deny_dropped: list[str] = []
    post_deny: list[dict[str, Any]] = []
    for c in candidates:
        url = c.get("url", "")
        if _is_denylisted(url):
            deny_dropped.append(_registered_domain(url) or url)
            log.info(
                "Competitor job %s dropping denylisted candidate %s",
                job_id, url,
            )
        else:
            post_deny.append(c)

    # Pass 2: HEAD probe (parallel, lenient).
    probe_dropped: list[str] = []
    kept: list[dict[str, Any]] = []
    if post_deny:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; StorefrontReviewer/1.0; "
                "+https://storefront-reviewer.example)"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        }

        async def _probe(c: dict[str, Any]) -> bool:
            url = c.get("url", "")
            # Two tries: once with strict cert verification, once without.
            # Real dead domains (timeout, DNS, conn refused) fail both.
            # Sites with dodgy intermediate cert chains pass the second —
            # browser-use on cloud handles those fine anyway.
            for verify in (True, False):
                try:
                    async with httpx.AsyncClient(
                        timeout=timeout_s,
                        follow_redirects=True,
                        headers=headers,
                        verify=verify,
                    ) as client:
                        try:
                            r = await client.head(url)
                            if r.status_code in (405, 501):
                                r = await client.get(url)
                        except httpx.HTTPError:
                            r = await client.get(url)
                    # Lenient: treat anything < 500 as reachable. DTC
                    # sites commonly return 403 to bot-looking HEADs
                    # but serve browser-use fine.
                    return r.status_code < 500
                except (httpx.ConnectError, httpx.ConnectTimeout,
                        httpx.ReadTimeout, httpx.RemoteProtocolError):
                    # Dead domain / unreachable → try again w/o verify
                    # in case the only issue was a cert chain problem.
                    continue
                except Exception:  # noqa: BLE001
                    continue
            return False

        results = await asyncio.gather(
            *[_probe(c) for c in post_deny], return_exceptions=True
        )
        for c, ok in zip(post_deny, results):
            if ok is True:
                kept.append(c)
            else:
                probe_dropped.append(_registered_domain(c.get("url", "")) or c.get("url", ""))

    log.info(
        "Competitor job %s candidate filter: %d → %d "
        "(denylist dropped %d: %s; unreachable dropped %d: %s)",
        job_id,
        len(candidates),
        len(kept),
        len(deny_dropped),
        ", ".join(deny_dropped[:5]) + ("…" if len(deny_dropped) > 5 else ""),
        len(probe_dropped),
        ", ".join(probe_dropped[:5]) + ("…" if len(probe_dropped) > 5 else ""),
    )
    scan_log.append(
        job_id,
        {
            "step": 18,
            "source": "worker",
            "lane": "filter",
            "next_goal": (
                f"filtered {len(candidates)} → {len(kept)} candidates"
            ),
            "evaluation": (
                f"dropped {len(deny_dropped)} captcha-walled "
                f"+ {len(probe_dropped)} unreachable"
            ),
        },
    )
    return kept


async def _run_demo(job_id: str, store_url: str, prompt: str | None, hint: str | None) -> None:
    await update_competitor_job(job_id, status="running", progress=0.1)
    scan_log.append(job_id, {"step": 0, "next_goal": "running in demo mode"})
    await asyncio.sleep(0.4)
    await update_competitor_job(job_id, progress=0.35)
    await asyncio.sleep(0.4)

    k = min(settings.max_competitors, 4)
    for comp in DEMO_COMPETITORS[:k]:
        await insert_competitor_result(job_id, dict(comp))
        await asyncio.sleep(0.15)

    await update_competitor_job(job_id, progress=0.75)
    scan_log.append(
        job_id, {"step": 1, "next_goal": f"inserted {k} demo competitors"}
    )
    await asyncio.sleep(0.3)
    await generate_competitor_report(job_id, store_url)
    await update_competitor_job(job_id, status="done", progress=1.0)
    scan_log.append(job_id, {"step": 2, "next_goal": "done"})


def _sanitize_untrusted(s: str | None, *, max_len: int = 2000) -> str:
    """Strip anything that could punch out of our ``<<<USER_INPUT>>>`` block
    and cap length. Paired with the system-prompt instruction telling Claude
    to treat the block contents as data."""
    if not s:
        return "(none)"
    cleaned = (
        s.replace("<<<USER_INPUT>>>", "")
        .replace("<<<END_USER_INPUT>>>", "")
    )
    # Collapse control chars that might fool log viewers / prompt parsers.
    cleaned = "".join(c for c in cleaned if c == "\n" or c >= " ")
    return cleaned[:max_len]


def _compose_notes(
    *,
    rationale: str,
    shipping_note: str,
    notes: str,
    promos: list[str],
    fees: Any = None,
    pages_visited: int | None = None,
) -> str:
    pieces: list[str] = []
    for piece in (rationale, shipping_note, notes):
        piece = (piece or "").strip()
        if piece:
            pieces.append(piece)
    promos_clean = [p.strip() for p in (promos or []) if p and p.strip()]
    if promos_clean:
        pieces.append(f"promos: {', '.join(promos_clean)}")
    if isinstance(fees, (int, float)):
        pieces.append(f"fees: ${float(fees):.2f}")
    if isinstance(pages_visited, int) and pages_visited > 0:
        pieces.append(f"pages visited: {pages_visited}")
    combined = " | ".join(pieces)
    if len(combined) > 500:
        combined = combined[:497] + "..."
    return combined


async def _browse_one(
    candidate: dict[str, Any],
    *,
    job_id: str,
    sem: asyncio.Semaphore,
    idx: int,
    hint: str | None = None,
    other_products: list[str] | None = None,
    target_items_count: int = 3,
) -> dict[str, Any] | None:
    raw_url = candidate.get("url", "")
    raw_name = candidate.get("name") or f"Competitor {idx+1}"
    # Strip control chars + newlines so a nasty name can't corrupt the
    # lane identifier or scan_log evaluation strings.
    name = (
        "".join(c for c in str(raw_name) if c >= " " and c != "\n")
        .strip()[:120]
    ) or f"Competitor {idx+1}"
    rationale = candidate.get("rationale", "") or ""
    try:
        url = validate_public_url(raw_url)
    except UnsafeURLError as e:
        log.info(
            "Competitor job %s dropping candidate URL %r: %s", job_id, raw_url, e
        )
        scan_log.append(
            job_id,
            {
                "step": 200 + idx,
                "next_goal": f"skipped {name}",
                "evaluation": f"unsafe URL: {e}",
            },
        )
        return None

    # Candidate idx gets a 1000-wide step range so browser-use's native 1..N
    # step numbers for this candidate never collide with worker stage markers
    # (0..9) or with other candidates.
    step_offset = 1000 + idx * 100
    snapshot: dict[str, Any] | None = None
    lane = f"cart: {name}"
    async with sem:
        for attempt in range(1, _MAX_BROWSE_ATTEMPTS + 1):
            scan_log.append(
                job_id,
                {
                    "step": step_offset - 1,
                    "lane": lane,
                    "next_goal": (
                        f"browsing {name}"
                        if attempt == 1
                        else f"retrying {name} (attempt {attempt}/{_MAX_BROWSE_ATTEMPTS})"
                    ),
                    "evaluation": url,
                },
            )
            try:
                attempt_offset = step_offset + (attempt - 1) * 10
                snapshot = await extract_checkout_snapshot(
                    url,
                    product_hint=hint,
                    scan_id=job_id,
                    step_offset=attempt_offset,
                    lane=lane,
                    other_products=other_products,
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "Competitor job %s snapshot attempt %d failed for %s: %s",
                    job_id, attempt, url, e,
                )
                snapshot = None
                continue
            # Break when the snapshot is usable. With catalog-first
            # extraction, a captured catalog `price` is already valuable
            # even if the cart walk couldn't read shipping/tax — no need
            # to retry in that case.
            if not snapshot.get("is_fallback") and (
                snapshot.get("reached_checkout")
                or isinstance(snapshot.get("price"), (int, float))
            ):
                break
            # Fallback OR no price captured → retry.
            if attempt < _MAX_BROWSE_ATTEMPTS:
                log.info(
                    "Competitor job %s %s no price captured (fallback=%s, "
                    "reached=%s); retrying",
                    job_id, url,
                    bool(snapshot.get("is_fallback")),
                    bool(snapshot.get("reached_checkout")),
                )

        # Qualification: competitor is kept if we captured at least 1 of
        # the target items' prices (main product OR any ancillary lookup).
        # Loose threshold — we only need one comparable price to include
        # a competitor in the synthesis.
        def _priced_count(snap: dict[str, Any] | None) -> int:
            if not snap:
                return 0
            n = int(isinstance(snap.get("price"), (int, float)))
            for p in snap.get("other_product_prices") or []:
                raw = p.get("price") if isinstance(p, dict) else getattr(p, "price", None)
                if isinstance(raw, (int, float)):
                    n += 1
            return n

        required = 1
        priced = _priced_count(snapshot)
        # Tri-state qualification:
        #   FULL     — priced >= required: first-class snapshot
        #   PARTIAL  — priced == 1 < required: kept as tie-breaker when
        #              the pipeline is starved of full successes
        #   REJECTED — fallback snapshot OR priced == 0: useless
        is_partial = False
        if snapshot is None or snapshot.get("is_fallback") or priced < 1:
            log.info(
                "Competitor job %s giving up on %s after %d attempts "
                "(priced=%d/%d, need %d)",
                job_id, url, _MAX_BROWSE_ATTEMPTS, priced,
                max(1, target_items_count), required,
            )
            scan_log.append(
                job_id,
                {
                    "step": step_offset - 1,
                    "lane": lane,
                    "next_goal": f"skipped {name} after {_MAX_BROWSE_ATTEMPTS} attempts",
                    "evaluation": (
                        f"only {priced}/{max(1, target_items_count)} "
                        "item prices captured — not scrape-able"
                    ),
                },
            )
            return None
        if priced < required:
            is_partial = True
            log.info(
                "Competitor job %s accepting %s as PARTIAL "
                "(priced=%d/%d, wanted %d)",
                job_id, url, priced, max(1, target_items_count), required,
            )

    promos = snapshot.get("promos") or []
    price = snapshot.get("price")
    shipping = snapshot.get("shipping")
    tax = snapshot.get("tax")
    fees = snapshot.get("fees")
    checkout_total = snapshot.get("checkout_total")
    discount_code = snapshot.get("discount_code")
    discount_amount = snapshot.get("discount_amount")
    reached_checkout = bool(snapshot.get("reached_checkout"))
    pages_visited = snapshot.get("pages_visited")
    # product_url comes from the agent — validate before we store it in
    # the DB and render it as an <a href> in the UI. Fall back to the
    # already-validated candidate URL on any failure.
    raw_product_url = snapshot.get("product_url") or ""
    product_url: str | None
    if raw_product_url:
        try:
            product_url = validate_public_url(raw_product_url)
        except UnsafeURLError as e:
            log.info(
                "Competitor job %s dropping unsafe product_url %r: %s",
                job_id, raw_product_url, e,
            )
            product_url = None
    else:
        product_url = None
    featured_product = snapshot.get("featured_product", "") or ""
    is_fallback = bool(snapshot.get("is_fallback"))
    fallback_tag = (
        "[placeholder data — browse failed] " if is_fallback
        else ("[partial data] " if is_partial else "")
    )
    notes_text = fallback_tag + _compose_notes(
        rationale=rationale,
        shipping_note=snapshot.get("shipping_note", "") or "",
        notes=snapshot.get("notes", "") or "",
        promos=promos,
        fees=fees,
        pages_visited=pages_visited if isinstance(pages_visited, int) else None,
    )
    if len(notes_text) > 500:
        notes_text = notes_text[:497] + "..."
    result = {
        "name": name,
        "url": product_url or snapshot.get("url", url),
        "price": price,
        "shipping": shipping,
        "tax": tax,
        "discount": discount_code or (promos[0] if promos else None),
        "checkout_total": checkout_total,
        "notes": notes_text,
        # raw_data persists the side-collected prices so the report can
        # build a top-3 shared-products × competitors matrix table.
        "raw_data": {
            "other_product_prices": snapshot.get("other_product_prices") or [],
        },
    }
    await insert_competitor_result(job_id, result)
    total_str = (
        f"${float(checkout_total):.2f}"
        if isinstance(checkout_total, (int, float))
        else "—"
    )
    reached_suffix = "" if reached_checkout else " (not reached)"
    # Log what we got + what's missing, per field, so partial-data rows
    # are easy to diagnose from logs alone.
    missing_fields = [
        name for (name, val) in (
            ("price", price),
            ("shipping", shipping),
            ("tax", tax),
            ("checkout_total", checkout_total),
        )
        if not isinstance(val, (int, float))
    ]
    ancillary = len(snapshot.get("other_product_prices") or [])
    log.info(
        "Competitor job %s persisted %s: price=%s ship=%s tax=%s "
        "total=%s ancillary=%d reached=%s%s%s",
        job_id, name,
        f"${float(price):.2f}" if isinstance(price, (int, float)) else "—",
        f"${float(shipping):.2f}" if isinstance(shipping, (int, float)) else "—",
        f"${float(tax):.2f}" if isinstance(tax, (int, float)) else "—",
        total_str,
        ancillary,
        reached_checkout,
        reached_suffix,
        (f" missing={','.join(missing_fields)}" if missing_fields else ""),
    )
    scan_log.append(
        job_id,
        {
            "step": step_offset - 2,
            "lane": lane,
            "next_goal": (
                f"persisted {name} (placeholder)" if is_fallback
                else f"persisted {name}: total={total_str}{reached_suffix}"
            ),
            "evaluation": (
                f"price={price} shipping={shipping} tax={tax} total={checkout_total}"
                + (" [fallback]" if is_fallback else "")
            ),
        },
    )
    # Return snapshot + candidate fields for synthesis input.
    return {
        "name": name,
        "url": product_url or snapshot.get("url", url),
        "product_url": product_url,
        "title": snapshot.get("title", ""),
        "featured_product": featured_product,
        "price": price,
        "shipping": shipping,
        "tax": tax,
        "fees": fees,
        "discount_code": discount_code,
        "discount_amount": discount_amount,
        "checkout_total": checkout_total,
        "reached_checkout": reached_checkout,
        "pages_visited": pages_visited,
        "promos": promos,
        "shipping_note": snapshot.get("shipping_note", "") or "",
        "notes": snapshot.get("notes", "") or "",
        "rationale": rationale,
        "is_fallback": is_fallback,
        "is_partial": is_partial,
        "other_product_prices": snapshot.get("other_product_prices") or [],
    }


async def _run_live(
    job_id: str, store_url: str, prompt: str | None, hint: str | None
) -> None:
    await update_competitor_job(job_id, status="running", progress=0.05)
    cancellation.raise_if_cancelled(job_id)
    # ---- Stage 0: observe the target store itself -------------------------
    scan_log.append(
        job_id,
        {
            "step": 0,
            "source": "browser-use",
            "lane": "your store",
            "next_goal": f"observing your store {store_url}",
        },
    )
    try:
        target_snapshot = await extract_competitor_snapshot(
            store_url, scan_id=job_id, step_offset=500,
            lane="your store",
            is_target=True,
            custom_prompt=prompt,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "Competitor job %s could not browse target %s: %s",
            job_id, store_url, e,
        )
        target_snapshot = None
        scan_log.append(
            job_id,
            {
                "step": 1,
                "source": "worker",
                "lane": "your store",
                "next_goal": "target browse failed — comparison will proceed without baseline",
                "evaluation": str(e)[:200],
            },
        )

    client = ClaudeClient()

    # ---- Stage 0.5: normalize the target's top_products into generic
    # ---- product categories BEFORE discovery, so discovery can search
    # ---- for stores that actually carry those categories (instead of
    # ---- stores semantically similar to the target's URL, which often
    # ---- don't overlap on SKU coverage at all).
    shared_products = await _normalize_top_products(
        store_url=store_url,
        target_snapshot=target_snapshot,
        hint=hint,
        custom_prompt=prompt,
        client=client,
        job_id=job_id,
    )
    if not shared_products:
        shared_products = _shared_products_from_target(target_snapshot)
    # Sanitize category names before handing them to downstream Claude
    # prompts / URL-encoded search queries. Names may originate from raw
    # scraped SKUs (fallback path), so scrub injection markers + caps.
    target_categories = [
        _sanitize_untrusted(p["name"], max_len=80)
        for p in (shared_products or []) if p.get("name")
    ]
    target_categories = [
        c for c in target_categories if c and c != "(none)"
    ][:3]

    use_agent_discovery = cloud_enabled()

    candidates_raw: list[dict[str, Any]] = []

    if use_agent_discovery:
        scan_log.append(
            job_id,
            {
                "step": 10,
                "source": "browser-use",
                "lane": "discover: merge",
                "next_goal": (
                    "spinning up 4 parallel agents to scrape the web for "
                    f"competitors of {store_url}"
                ),
            },
        )
        try:
            candidates_raw = await discover_competitors_parallel(
                store_url=store_url,
                product_hint=_sanitize_untrusted(hint, max_len=500),
                custom_prompt=_sanitize_untrusted(prompt),
                target_categories=target_categories,
                scan_id=job_id,
                step_offset_base=30,
                per_agent_count=3,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Competitor job %s parallel discovery failed: %s", job_id, e)
            candidates_raw = []

    # Claude fallback when cloud discovery is disabled OR returned nothing.
    if not candidates_raw:
        scan_log.append(
            job_id,
            {
                "step": 10,
                "source": "claude",
                "lane": "claude: discovery",
                "next_goal": f"discovering competitors for {store_url}",
            },
        )
        discovery_prompt = prompts.COMPETITOR_DISCOVERY_PROMPT.format(
            store_url=store_url,
            product_hint=_sanitize_untrusted(hint, max_len=500),
            custom_prompt=_sanitize_untrusted(prompt),
            target_categories=(
                ", ".join(target_categories) if target_categories else "(none extracted)"
            ),
        )
        text = await client.complete(
            discovery_prompt,
            system=prompts.SYSTEM_COMPETITOR_DISCOVERY,
            max_tokens=1024,
        )
        candidates_raw = _extract_json_array(text)
    # Validate + dedupe by URL.
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in candidates_raw:
        if not isinstance(c, dict):
            continue
        raw_url = str(c.get("url", "")).strip()
        if not raw_url:
            continue
        try:
            safe = validate_public_url(raw_url)
        except UnsafeURLError as e:
            log.info(
                "Competitor job %s dropping candidate URL %r: %s",
                job_id, raw_url, e,
            )
            continue
        if safe in seen:
            continue
        seen.add(safe)
        candidates.append({**c, "url": safe})
        # Keep extras so drop-outs don't starve us of results.
        if len(candidates) >= settings.max_competitors + _DISCOVERY_SPARES:
            break

    log.info(
        "Competitor job %s discovery: raw=%d kept=%d (dropped %d invalid/dupe)",
        job_id,
        len(candidates_raw),
        len(candidates),
        len(candidates_raw) - len(candidates),
    )

    # Cheap filter: domain denylist + HEAD-probe reachability. Drops
    # captcha-walled retailers and dead domains BEFORE we pay the
    # browser-use session-start cost (~90s each). Keep the pre-filter
    # list so escalation can use it as negative examples.
    pre_filter_candidates = list(candidates)
    candidates = await _filter_candidates(candidates, job_id=job_id)

    if candidates:
        preview = ", ".join(c.get("name", "?") for c in candidates[:5])
        log.info(
            "Competitor job %s candidates: %s%s",
            job_id, preview, "…" if len(candidates) > 5 else "",
        )

    # If the filter killed every candidate (all denylisted/dead), try
    # one escalation Claude call to propose alternatives before giving
    # up. Saves the demo-fallback humiliation when discovery was noisy.
    if not candidates and pre_filter_candidates:
        log.info(
            "Competitor job %s: filter dropped all %d candidates — "
            "escalating immediately",
            job_id, len(pre_filter_candidates),
        )
        extra = await _escalate_candidates(
            store_url=store_url,
            target_categories=target_categories,
            failed_candidates=pre_filter_candidates,
            hint=hint,
            custom_prompt=prompt,
            client=client,
            job_id=job_id,
        )
        candidates = await _filter_candidates(extra, job_id=job_id)

    if not candidates:
        log.warning(
            "Competitor job %s has no reachable candidates after filter — "
            "falling back to demo",
            job_id,
        )
        raise DemoFallbackError("no reachable competitors after filter")

    cancellation.raise_if_cancelled(job_id)

    scan_log.append(
        job_id,
        {
            "step": 1,
            "next_goal": f"browsing {len(candidates)} competitors",
            "evaluation": ", ".join(c.get("name", "?") for c in candidates),
        },
    )
    await update_competitor_job(job_id, progress=0.22)

    # ---- Stage 1.5: shared_products was derived from target top_products
    # ---- via Claude normalization in Stage 0.5. If that produced
    # ---- nothing (empty target, both normalize + raw-SKU fallback
    # ---- failed), fall back to Claude's candidate-aware shared-products
    # ---- identification here so cart walks still have a product hint.
    if not shared_products:
        shared_products = await _identify_shared_products(
            store_url=store_url,
            target_snapshot=target_snapshot,
            candidates=candidates,
            hint=hint,
            custom_prompt=prompt,
            client=client,
            job_id=job_id,
        )
    if shared_products:
        log.info(
            "Competitor job %s identified %d shared product types: %s",
            job_id, len(shared_products),
            " | ".join(p.get("name", "?") for p in shared_products),
        )
    else:
        log.info(
            "Competitor job %s: no shared products identified; cart walks "
            "will use user hint %r",
            job_id, hint or "",
        )
    cart_hint_raw = (
        shared_products[0]["name"] if shared_products else hint or ""
    )
    # Strip control chars + newlines + cap length so whatever Claude
    # returned can't mangle the cart-walk task prompt f-string.
    cart_hint = (
        "".join(c for c in cart_hint_raw if c >= " " and c != "\n")
        .replace("'", "")
        .strip()[:120]
    )
    await update_competitor_job(job_id, progress=0.28)

    # Pass the 2nd + 3rd shared-product names so each cart walk can also
    # record their prices in passing (no extra clicks) for the pricing
    # matrix.
    other_product_names = [
        p["name"] for p in (shared_products or [])[1:3]
        if p.get("name")
    ]

    sem = asyncio.Semaphore(_BROWSE_CONCURRENCY)
    # Work through the ranked candidate list, keeping successful browses
    # as they arrive. Once we have max_competitors successes, cancel the
    # rest so we don't pay for cloud sessions we're about to discard.
    # How many items the target is being compared on. Qualification
    # threshold inside _browse_one scales off this.
    target_items_count = len(shared_products) if shared_products else 0
    tasks = [
        asyncio.create_task(
            _browse_one(
                c, job_id=job_id, sem=sem, idx=i,
                hint=cart_hint, other_products=other_product_names,
                target_items_count=target_items_count,
            )
        )
        for i, c in enumerate(candidates)
    ]
    full_snapshots: list[dict[str, Any]] = []
    partial_snapshots: list[dict[str, Any]] = []

    def _count_total() -> int:
        return len(full_snapshots) + len(partial_snapshots)

    def _absorb(result: dict[str, Any]) -> None:
        if result.get("is_partial"):
            partial_snapshots.append(result)
        else:
            full_snapshots.append(result)

    try:
        for fut in asyncio.as_completed(tasks):
            if cancellation.is_cancelled(job_id):
                log.info(
                    "Competitor job %s: cancellation detected mid-browse; "
                    "breaking out of cart-walk loop",
                    job_id,
                )
                break
            result = await fut
            if result is not None:
                _absorb(result)
                # Incremental progress so the bar doesn't sit at 0.28 for
                # minutes while cart walks run. 0.28 → ~0.70 across all
                # competitor successes (counts full + partial).
                pct = 0.28 + 0.42 * (
                    min(_count_total(), settings.max_competitors)
                    / max(1, settings.max_competitors)
                )
                await update_competitor_job(job_id, progress=pct)
                # Early-exit: enough FULL successes (best case), OR
                # enough total candidates have returned (bound worst-
                # case latency — if 2N candidates landed without hitting
                # max_competitors fulls, remaining ones probably won't
                # either, and we already have enough partials to show).
                if (
                    len(full_snapshots) >= settings.max_competitors
                    or _count_total() >= settings.max_competitors * 2
                ):
                    break
    finally:
        # Cancel any still-running browses; run_cloud_agent's finally
        # block will issue stop_task_and_session to release cloud slots.
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # If the user clicked Stop, bail before wasting tokens on synthesis.
    cancellation.raise_if_cancelled(job_id)

    total = _count_total()
    if total:
        scan_log.append(
            job_id,
            {
                "step": 98,
                "next_goal": (
                    f"collected {len(full_snapshots)} full + "
                    f"{len(partial_snapshots)} partial snapshots "
                    f"(target {settings.max_competitors}); cancelling "
                    "remaining browses"
                ),
            },
        )

    log.info(
        "Competitor job %s cart walks: %d full + %d partial (target %d)",
        job_id, len(full_snapshots), len(partial_snapshots),
        settings.max_competitors,
    )

    # ---- Escalation: if zero snapshots of any kind landed, ask Claude
    # ---- for a fresh candidate list avoiding the failed domains and
    # ---- retry ONCE before giving up.
    if total == 0 and not cancellation.is_cancelled(job_id):
        log.info(
            "Competitor job %s: zero snapshots — escalating with "
            "Claude for alt candidates",
            job_id,
        )
        extra_candidates = await _escalate_candidates(
            store_url=store_url,
            target_categories=target_categories,
            failed_candidates=candidates,
            hint=hint,
            custom_prompt=prompt,
            client=client,
            job_id=job_id,
        )
        extra_candidates = await _filter_candidates(
            extra_candidates, job_id=job_id
        )
        if extra_candidates:
            extra_sem = asyncio.Semaphore(_BROWSE_CONCURRENCY)
            extra_tasks = [
                asyncio.create_task(
                    _browse_one(
                        c, job_id=job_id, sem=extra_sem,
                        idx=len(candidates) + i,
                        hint=cart_hint, other_products=other_product_names,
                        target_items_count=target_items_count,
                    )
                )
                for i, c in enumerate(extra_candidates)
            ]
            try:
                for fut in asyncio.as_completed(extra_tasks):
                    if cancellation.is_cancelled(job_id):
                        break
                    result = await fut
                    if result is not None:
                        _absorb(result)
                        if (
                            len(full_snapshots) >= settings.max_competitors
                            or _count_total() >= settings.max_competitors * 2
                        ):
                            break
            finally:
                for t in extra_tasks:
                    if not t.done():
                        t.cancel()
                if extra_tasks:
                    await asyncio.gather(*extra_tasks, return_exceptions=True)
        total = _count_total()
        log.info(
            "Competitor job %s post-escalation: %d full + %d partial",
            job_id, len(full_snapshots), len(partial_snapshots),
        )

    # Merge: prefer FULL snapshots; use PARTIAL to top up to
    # max_competitors when full successes are scarce.
    snapshots_list = list(full_snapshots[: settings.max_competitors])
    need_more = settings.max_competitors - len(snapshots_list)
    if need_more > 0 and partial_snapshots:
        snapshots_list.extend(partial_snapshots[:need_more])

    if not snapshots_list:
        log.warning(
            "Competitor job %s: zero cart walks succeeded "
            "(including escalation) — falling back to demo",
            job_id,
        )
        raise DemoFallbackError(
            "no competitor snapshots captured (post-escalation)"
        )

    await update_competitor_job(job_id, progress=0.75)
    scan_log.append(
        job_id,
        {
            "step": 2,
            "source": "claude",
            "lane": "claude: synthesis",
            "next_goal": "synthesizing strategy brief",
            "evaluation": f"{len(snapshots_list)} snapshots captured",
        },
    )

    # Build the per-product price table (biggest delta vs. target first).
    price_table = _build_price_table(target_snapshot, snapshots_list)

    target_json = json.dumps(
        _target_for_prompt(store_url, target_snapshot), ensure_ascii=False
    )

    # If we identified a specific shared product, tell synthesis about it
    # — cart walks compared stores against THAT product, so Claude should
    # frame recommendations around it rather than the user's vague hint.
    synthesis_hint = cart_hint if shared_products else (hint or "")

    synthesis: dict[str, Any] | None = None
    try:
        synth_prompt = prompts.COMPETITOR_SYNTHESIS_PROMPT.format(
            store_url=store_url,
            product_hint=_sanitize_untrusted(synthesis_hint, max_len=500),
            target_json=target_json,
            competitors_json=json.dumps(snapshots_list, ensure_ascii=False),
        )
        synth_text = await client.complete(
            synth_prompt,
            system=prompts.SYSTEM_COMPETITOR_SYNTHESIS,
            max_tokens=2048,
        )
        parsed = _extract_json_object(synth_text)
        if parsed and isinstance(parsed, dict):
            synthesis = {
                "summary_markdown": str(parsed.get("summary_markdown", "")).strip(),
                "recommendations": [
                    str(r) for r in (parsed.get("recommendations") or []) if r
                ],
                "scores": {
                    k: max(0, min(100, int(v)))
                    for k, v in (parsed.get("scores") or {}).items()
                    if isinstance(v, (int, float))
                },
            }
    except DemoFallbackError as e:
        log.info("Competitor job %s synthesis Claude call failed: %s", job_id, e)
        synthesis = None
    except Exception as e:  # noqa: BLE001
        log.warning("Competitor job %s synthesis parse error: %s", job_id, e)
        synthesis = None

    if synthesis is None:
        # Fallback: derive a basic summary from the snapshot list.
        log.warning(
            "Competitor job %s synthesis unavailable — using deterministic "
            "fallback brief (%d snapshots)",
            job_id, len(snapshots_list),
        )
        synthesis = _fallback_synthesis(store_url, snapshots_list)
        scan_log.append(
            job_id,
            {
                "step": 3,
                "next_goal": "synthesis fallback applied",
                "evaluation": "Claude synthesis unavailable or unparseable",
            },
        )
    else:
        scores = synthesis.get("scores", {})
        log.info(
            "Competitor job %s synthesis ok: %d recs, scores=%s",
            job_id,
            len(synthesis.get("recommendations", [])),
            scores,
        )
        scan_log.append(
            job_id,
            {
                "step": 3,
                "next_goal": "synthesis complete",
                "evaluation": (
                    f"{len(synthesis.get('recommendations', []))} recs"
                ),
            },
        )

    await update_competitor_job(job_id, progress=0.9)
    await generate_competitor_report(
        job_id, store_url, synthesis=synthesis, price_table=price_table,
        shared_products=shared_products, target_snapshot=target_snapshot,
    )
    await update_competitor_job(job_id, status="done", progress=1.0)
    scan_log.append(job_id, {"step": 4, "next_goal": "done"})


def _target_for_prompt(
    store_url: str, target: dict[str, Any] | None
) -> dict[str, Any]:
    """Shape the target snapshot for the synthesis prompt. If the target
    couldn't be browsed (or fell back to placeholder), still emit a stub
    so Claude always sees the target's URL."""
    if target is None:
        return {
            "url": store_url,
            "title": "",
            "featured_product": "",
            "featured_price": None,
            "promos": [],
            "shipping_note": "",
            "notes": "",
            "is_fallback": True,
        }
    return {
        "url": target.get("url", store_url),
        "title": target.get("title", ""),
        "featured_product": target.get("featured_product", ""),
        "featured_price": target.get("featured_price"),
        "promos": target.get("promos") or [],
        "shipping_note": target.get("shipping_note", ""),
        "notes": target.get("notes", ""),
        "is_fallback": bool(target.get("is_fallback")),
    }


def _build_price_table(
    target: dict[str, Any] | None, snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One row per (competitor, product) plus a leading target row, sorted
    so competitors with the biggest absolute delta vs. target come first.

    A target row is always emitted (as "You") even if featured_price is
    None — callers can render it regardless.
    """
    target_price: float | None = None
    target_product = ""
    if target is not None:
        tp = target.get("featured_price")
        if isinstance(tp, (int, float)):
            target_price = float(tp)
        target_product = target.get("featured_product", "") or ""

    rows: list[dict[str, Any]] = []
    for s in snapshots:
        # Target uses featured_price (advertised subtotal, pre-tax/ship),
        # so we compare apples-to-apples: prefer competitor's cart subtotal
        # (`price`), NOT checkout_total (which bundles shipping + tax).
        # checkout_total is only a last-resort fallback.
        price = s.get("price")
        if not isinstance(price, (int, float)):
            price = s.get("checkout_total")
        if not isinstance(price, (int, float)):
            continue
        delta: float | None
        if target_price is None:
            delta = None
        else:
            delta = float(price) - target_price
        rows.append(
            {
                "store": s.get("name", "?"),
                "product": s.get("featured_product", "") or "(unnamed)",
                "price": float(price),
                "delta_vs_target": delta,
                "is_fallback": bool(s.get("is_fallback")),
            }
        )

    # Sort by absolute delta DESC when we have a target baseline;
    # otherwise by price DESC.
    if target_price is not None:
        rows.sort(
            key=lambda r: abs(r["delta_vs_target"] or 0.0),
            reverse=True,
        )
    else:
        rows.sort(key=lambda r: r["price"], reverse=True)

    # Prepend the target row.
    rows.insert(
        0,
        {
            "store": "You",
            "product": target_product or "(your featured product)",
            "price": target_price,
            "delta_vs_target": 0.0 if target_price is not None else None,
            "is_fallback": bool(target and target.get("is_fallback")),
            "is_target": True,
        },
    )
    return rows


def _fallback_synthesis(
    store_url: str, snapshots: list[dict[str, Any]]
) -> dict[str, Any]:
    names = [s.get("name", "?") for s in snapshots]
    prices = [
        s.get("checkout_total") if isinstance(s.get("checkout_total"), (int, float))
        else s.get("price")
        for s in snapshots
        if isinstance(s.get("checkout_total"), (int, float))
        or isinstance(s.get("price"), (int, float))
    ]
    if prices:
        lo = min(prices)
        hi = max(prices)
        price_line = (
            f"Competitor featured prices range **${lo:.2f} – ${hi:.2f}** "
            f"across {len(prices)} stores with visible pricing."
        )
    else:
        price_line = "No featured prices were captured from competitor pages."
    summary_md = (
        f"# Competitor Comparison\n\n"
        f"Compared **{store_url}** against {len(snapshots)} competitors: "
        f"{', '.join(names)}.\n\n{price_line}"
    )
    recs = [
        "Surface any active promo codes prominently on the PDP.",
        "Offer a free-shipping threshold competitive with the set above.",
        "Highlight total-at-cart early to reduce checkout abandonment.",
    ]
    return {
        "summary_markdown": summary_md,
        "recommendations": recs,
        "scores": {"pricing": 60, "value": 60, "experience": 70},
    }


def _shared_products_from_target(
    target_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Raw fallback: use the target's specific SKUs verbatim as the match
    set. Only used if Claude normalization fails — specific SKUs rarely
    overlap across stores, but something is better than nothing."""
    if not target_snapshot or target_snapshot.get("is_fallback"):
        return []
    items = target_snapshot.get("top_products") or []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("product") or "").strip()
        if not name:
            continue
        out.append({
            "name": name[:120],
            "description": "from target store's top products",
            "match_likelihood": 80,
        })
        if len(out) >= 3:
            break
    return out


async def _normalize_top_products(
    *,
    store_url: str,
    target_snapshot: dict[str, Any] | None,
    hint: str | None,
    custom_prompt: str | None,
    client: ClaudeClient,
    job_id: str,
) -> list[dict[str, Any]]:
    """Convert the target's specific SKU names into generic category terms
    (e.g. 'Adidas Samba OG Crocodile Silver' → 'lifestyle sneaker') so
    cart walks on OTHER storefronts stand a chance of finding comparable
    items. Returns ``[]`` when the target has no top_products or Claude
    fails — caller falls back to :func:`_shared_products_from_target`.
    """
    if not target_snapshot or target_snapshot.get("is_fallback"):
        return []
    raw_items = target_snapshot.get("top_products") or []
    # SKU names come from scraped page content (untrusted). Scrub the
    # injection markers + control chars before sending to Claude.
    top_products = [
        {
            "product": _sanitize_untrusted(
                str(it.get("product") or ""), max_len=160
            ),
            "price": it.get("price") if isinstance(it.get("price"), (int, float)) else None,
        }
        for it in raw_items
        if isinstance(it, dict) and str(it.get("product") or "").strip()
    ][:3]
    # Drop items that ended up as "(none)" / empty after sanitization.
    top_products = [
        tp for tp in top_products
        if tp["product"] and tp["product"] != "(none)"
    ]
    if not top_products:
        return []

    scan_log.append(
        job_id,
        {
            "step": 13,
            "source": "claude",
            "lane": "claude: normalize",
            "next_goal": (
                f"normalizing {len(top_products)} target SKUs into "
                "generic product categories"
            ),
        },
    )
    try:
        prompt_text = prompts.NORMALIZE_PRODUCTS_PROMPT.format(
            store_url=store_url,
            product_hint=_sanitize_untrusted(hint, max_len=500),
            custom_prompt=_sanitize_untrusted(custom_prompt),
            top_products_json=json.dumps(top_products, ensure_ascii=False),
        )
        text = await client.complete(
            prompt_text,
            system=prompts.SYSTEM_NORMALIZE_PRODUCTS,
            max_tokens=512,
        )
        parsed = _extract_json_object(text)
    except DemoFallbackError as e:
        log.info("normalize-top-products Claude call failed: %s", e)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("normalize-top-products parse error: %s", e)
        return []

    if not isinstance(parsed, dict):
        return []
    raw_products = parsed.get("products") or []
    if not isinstance(raw_products, list):
        return []
    out: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in raw_products[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()[:120]
        desc = str(item.get("description", "")).strip()[:240]
        if not name or name in seen_names:
            # Broad categories will often collapse (e.g. 2 SKUs both →
            # 'sneakers'); dedup so cart_hint + other_products don't
            # repeat the same category.
            continue
        seen_names.add(name)
        out.append({
            "name": name,
            "description": desc,
            "match_likelihood": 85,
        })

    if out:
        scan_log.append(
            job_id,
            {
                "step": 14,
                "source": "claude",
                "lane": "claude: normalize",
                "next_goal": f"normalized to {len(out)} generic categories",
                "evaluation": " | ".join(p["name"] for p in out),
            },
        )
    return out


async def _escalate_candidates(
    *,
    store_url: str,
    target_categories: list[str],
    failed_candidates: list[dict[str, Any]],
    hint: str | None,
    custom_prompt: str | None,
    client: ClaudeClient,
    job_id: str,
) -> list[dict[str, Any]]:
    """Ask Claude for 3 alternative candidates after the initial set all
    failed. Negatively conditions the prompt with the failed domain list
    so Claude doesn't suggest close variants. Returns ``[]`` if Claude
    fails or returns nothing. Returned candidates still go through the
    same URL validation + filter pipeline as the initial set."""
    failed_display = []
    failed_domains: set[str] = set()
    for c in failed_candidates[:12]:
        name = str(c.get("name", "?"))[:60]
        domain = _registered_domain(c.get("url", ""))
        if domain:
            failed_domains.add(domain)
            failed_display.append(f"- {name} ({domain})")
    if not failed_display:
        failed_display = ["- (none recorded)"]

    scan_log.append(
        job_id,
        {
            "step": 96,
            "source": "claude",
            "lane": "claude: escalation",
            "next_goal": (
                "all candidates failed — asking Claude for alternatives"
            ),
            "evaluation": (
                f"{len(failed_candidates)} failed, "
                f"target categories: {', '.join(target_categories) or 'none'}"
            ),
        },
    )
    try:
        prompt_text = prompts.ESCALATE_CANDIDATES_PROMPT.format(
            store_url=store_url,
            target_categories=(
                ", ".join(target_categories) if target_categories else "(none extracted)"
            ),
            product_hint=_sanitize_untrusted(hint, max_len=500),
            custom_prompt=_sanitize_untrusted(custom_prompt),
            failed_list="\n".join(failed_display),
        )
        text = await client.complete(
            prompt_text,
            system=prompts.SYSTEM_ESCALATE_CANDIDATES,
            max_tokens=512,
        )
        raw = _extract_json_array(text)
    except DemoFallbackError as e:
        log.info("escalation Claude call failed: %s", e)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("escalation parse error: %s", e)
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in raw:
        if not isinstance(c, dict):
            continue
        raw_url = str(c.get("url", "")).strip()
        if not raw_url:
            continue
        try:
            safe = validate_public_url(raw_url)
        except UnsafeURLError:
            continue
        dom = _registered_domain(safe)
        # Drop anything Claude accidentally re-proposed.
        if dom in failed_domains or safe in seen:
            continue
        seen.add(safe)
        out.append({**c, "url": safe})
        if len(out) >= 3:
            break

    log.info(
        "Competitor job %s escalation returned %d fresh candidates: %s",
        job_id, len(out),
        ", ".join(c.get("name", "?") for c in out),
    )
    if out:
        scan_log.append(
            job_id,
            {
                "step": 97,
                "source": "claude",
                "lane": "claude: escalation",
                "next_goal": f"retrying with {len(out)} fresh candidates",
                "evaluation": ", ".join(
                    c.get("name", "?") for c in out
                ),
            },
        )
    return out


async def _identify_shared_products(
    *,
    store_url: str,
    target_snapshot: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    hint: str | None,
    custom_prompt: str | None,
    client: ClaudeClient,
    job_id: str,
) -> list[dict[str, Any]]:
    """Claude names the 3 product types shared across target + competitors.

    Returns a list of ``{name, description, match_likelihood}`` dicts
    ranked most-shared first. Empty list on any failure — caller falls
    back to the user's plain product_hint.
    """
    scan_log.append(
        job_id,
        {
            "step": 15,
            "source": "claude",
            "lane": "claude: shared products",
            "next_goal": "identifying top-3 shared product types",
            "evaluation": f"{len(candidates)} candidates",
        },
    )
    competitor_list = [
        {"name": c.get("name", "?"), "url": c.get("url", ""),
         "rationale": (c.get("rationale") or "")[:200]}
        for c in candidates
    ]
    target_featured = ""
    target_price_str = "unknown"
    if target_snapshot:
        target_featured = target_snapshot.get("featured_product", "") or ""
        tp = target_snapshot.get("featured_price")
        if isinstance(tp, (int, float)):
            target_price_str = f"${float(tp):.2f}"
    try:
        prompt_text = prompts.SHARED_PRODUCTS_PROMPT.format(
            store_url=store_url,
            target_featured_product=target_featured or "(unknown)",
            target_featured_price=target_price_str,
            product_hint=_sanitize_untrusted(hint, max_len=500),
            custom_prompt=_sanitize_untrusted(custom_prompt),
            competitors_json=json.dumps(competitor_list, ensure_ascii=False),
        )
        text = await client.complete(
            prompt_text,
            system=prompts.SYSTEM_SHARED_PRODUCTS,
            max_tokens=512,
        )
        parsed = _extract_json_object(text)
    except DemoFallbackError as e:
        log.info("shared-products Claude call failed: %s", e)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("shared-products parse error: %s", e)
        return []

    if not isinstance(parsed, dict):
        return []
    raw_products = parsed.get("products") or []
    if not isinstance(raw_products, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_products[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:120]
        desc = str(item.get("description", "")).strip()[:240]
        likelihood_raw = item.get("match_likelihood", 50)
        try:
            likelihood = max(0, min(100, int(likelihood_raw)))
        except (TypeError, ValueError):
            likelihood = 50
        if not name:
            continue
        out.append({
            "name": name,
            "description": desc,
            "match_likelihood": likelihood,
        })

    if out:
        scan_log.append(
            job_id,
            {
                "step": 16,
                "source": "claude",
                "lane": "claude: shared products",
                "next_goal": f"found {len(out)} shared products",
                "evaluation": " | ".join(p["name"] for p in out),
            },
        )
    return out


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
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
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            return []
    return []


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                try:
                    return json.loads(p)
                except Exception:  # noqa: BLE001
                    continue
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


async def run_competitor_job(
    job_id: str, store_url: str, prompt: str | None, hint: str | None
) -> None:
    """Entry point called from FastAPI BackgroundTasks."""
    metrics.inc(
        "competitor_jobs_started_total",
        mode="demo" if is_demo_mode() else "live",
    )
    try:
        if is_demo_mode():
            await _run_demo(job_id, store_url, prompt, hint)
        else:
            try:
                await _run_live(job_id, store_url, prompt, hint)
            except DemoFallbackError as e:
                log.info(
                    "Competitor job %s falling back to demo: %s", job_id, e
                )
                scan_log.append(
                    job_id,
                    {
                        "step": 99,
                        "next_goal": "falling back to demo",
                        "evaluation": str(e)[:200],
                    },
                )
                await _run_demo(job_id, store_url, prompt, hint)
        metrics.inc("competitor_jobs_completed_total")
    except CancelledByUser:
        log.info("Competitor job %s cancelled by user — exiting cleanly", job_id)
        metrics.inc("competitor_jobs_cancelled_total")
        # DB status already set to "cancelled" by the route handler that
        # fired the cancel; don't overwrite it.
        scan_log.append(
            job_id,
            {
                "step": 99,
                "next_goal": "cancelled by user",
                "evaluation": "stop requested",
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Competitor job %s failed: %s", job_id, e)
        metrics.inc("competitor_jobs_failed_total", reason="exception")
        try:
            await update_competitor_job(
                job_id, status="failed", error=str(e), progress=1.0
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to mark competitor job %s as failed", job_id)
    finally:
        cancellation.clear(job_id)
