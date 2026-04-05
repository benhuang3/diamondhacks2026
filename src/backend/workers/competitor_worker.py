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
from ..observability import scan_log
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
            # Accept when checkout was reached and we're not in fallback mode.
            if (
                not snapshot.get("is_fallback")
                and snapshot.get("reached_checkout")
            ):
                break
            # Either fallback or checkout not reached → retry.
            if attempt < _MAX_BROWSE_ATTEMPTS:
                log.info(
                    "Competitor job %s %s did not reach checkout (fallback=%s); retrying",
                    job_id, url, bool(snapshot.get("is_fallback")),
                )

        if (
            snapshot is None
            or snapshot.get("is_fallback")
            or not snapshot.get("reached_checkout")
        ):
            log.info(
                "Competitor job %s giving up on %s after %d attempts",
                job_id, url, _MAX_BROWSE_ATTEMPTS,
            )
            scan_log.append(
                job_id,
                {
                    "step": step_offset - 1,
                    "lane": lane,
                    "next_goal": f"skipped {name} after {_MAX_BROWSE_ATTEMPTS} attempts",
                    "evaluation": "site unavailable / not scrape-able",
                },
            )
            return None

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
        "[placeholder data — browse failed] " if is_fallback else ""
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
    log.info(
        "Competitor job %s persisted %s: total=%s%s",
        job_id, name, total_str, reached_suffix,
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
        "other_product_prices": snapshot.get("other_product_prices") or [],
    }


async def _run_live(
    job_id: str, store_url: str, prompt: str | None, hint: str | None
) -> None:
    await update_competitor_job(job_id, status="running", progress=0.05)
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

    use_agent_discovery = cloud_enabled()

    client = ClaudeClient()
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
                scan_id=job_id,
                step_offset_base=30,
                per_agent_count=5,
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

    if not candidates:
        raise DemoFallbackError("no competitors discovered")

    scan_log.append(
        job_id,
        {
            "step": 1,
            "next_goal": f"browsing {len(candidates)} competitors",
            "evaluation": ", ".join(c.get("name", "?") for c in candidates),
        },
    )
    await update_competitor_job(job_id, progress=0.22)

    # ---- Stage 1.5: identify the 3 product types target + competitors
    # ---- all likely sell. Top-ranked one becomes the hint for cart walks.
    shared_products = await _identify_shared_products(
        store_url=store_url,
        target_snapshot=target_snapshot,
        candidates=candidates,
        hint=hint,
        custom_prompt=prompt,
        client=client,
        job_id=job_id,
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
    tasks = [
        asyncio.create_task(
            _browse_one(
                c, job_id=job_id, sem=sem, idx=i,
                hint=cart_hint, other_products=other_product_names,
            )
        )
        for i, c in enumerate(candidates)
    ]
    snapshots_list: list[dict[str, Any]] = []
    try:
        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result is not None:
                snapshots_list.append(result)
                # Incremental progress so the bar doesn't sit at 0.28 for
                # minutes while cart walks run. 0.28 → ~0.70 across all
                # competitor successes.
                pct = 0.28 + 0.42 * (
                    min(len(snapshots_list), settings.max_competitors)
                    / max(1, settings.max_competitors)
                )
                await update_competitor_job(job_id, progress=pct)
                if len(snapshots_list) >= settings.max_competitors:
                    break
    finally:
        # Cancel any still-running browses; run_cloud_agent's finally
        # block will issue stop_task_and_session to release cloud slots.
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    if snapshots_list:
        scan_log.append(
            job_id,
            {
                "step": 98,
                "next_goal": (
                    f"collected {len(snapshots_list)}/"
                    f"{settings.max_competitors} successful snapshots; "
                    "cancelling remaining browses"
                ),
            },
        )

    if not snapshots_list:
        raise DemoFallbackError("no competitor snapshots captured")

    # Note: _browse_one already filters out fallback + not-reached
    # snapshots, so snapshots_list contains only clean live results here.

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
        shared_products=shared_products,
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
    except Exception as e:  # noqa: BLE001
        log.exception("Competitor job %s failed: %s", job_id, e)
        metrics.inc("competitor_jobs_failed_total", reason="exception")
        try:
            await update_competitor_job(
                job_id, status="failed", error=str(e), progress=1.0
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to mark competitor job %s as failed", job_id)
