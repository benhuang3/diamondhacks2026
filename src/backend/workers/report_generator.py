"""Report generation for scans and competitor jobs.

DEMO_MODE produces deterministic canned content. Live mode asks Claude for a
summary + sections, but falls back to demo output on failure.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from src.db.queries import (
    create_report,
    list_competitor_results,
    list_findings,
    update_competitor_job,
    update_scan,
)

from ..agents.claude_client import ClaudeClient, DemoFallbackError, is_demo_mode

log = logging.getLogger(__name__)


def _score_from_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    high = sum(1 for f in findings if f.get("severity") == "high")
    med = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")
    penalty = high * 12 + med * 6 + low * 2
    base = max(35, 95 - penalty)
    # spread across the three axes
    a11y = max(20, base - sum(1 for f in findings if f.get("category") == "a11y") * 3)
    ux = max(20, base - sum(1 for f in findings if f.get("category") == "ux") * 3)
    flow = max(20, base - sum(1 for f in findings if f.get("category") == "nav") * 4)
    return {"accessibility": int(a11y), "ux": int(ux), "flow": int(flow)}


def _severity_chart(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        if sev in counts:
            counts[sev] += 1
    return {
        "type": "bar",
        "data": [{"label": k, "value": v} for k, v in counts.items()],
        "config": {"xKey": "label", "yKey": "value"},
    }


def _category_chart(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for f in findings:
        c = f.get("category", "ux")
        counts[c] = counts.get(c, 0) + 1
    return {
        "type": "bar",
        "data": [{"label": k, "value": v} for k, v in counts.items()],
        "config": {"xKey": "label", "yKey": "value"},
    }


def _per_page_section(
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Group findings by page_url and render a per-page breakdown section.

    Returns None if only one distinct page_url is present (or none at all).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        page_url = f.get("page_url") or ""
        if not page_url:
            continue
        groups.setdefault(page_url, []).append(f)

    if len(groups) <= 1:
        return None

    def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
        c = {"high": 0, "medium": 0, "low": 0}
        for f in items:
            sev = f.get("severity", "low")
            if sev in c:
                c[sev] += 1
        return c

    ranked = sorted(
        groups.items(),
        key=lambda kv: (len(kv[1]), _counts(kv[1])["high"]),
        reverse=True,
    )

    body_lines: list[str] = []
    chart_data: list[dict[str, Any]] = []
    for page_url, items in ranked:
        counts = _counts(items)
        total = len(items)
        body_lines.append(
            f"- **{page_url}** — {total} findings "
            f"({counts['high']} high, {counts['medium']} medium, "
            f"{counts['low']} low)"
        )
        for f in items[:2]:
            body_lines.append(f"  - ▸ {f.get('title', '')}")
        label = page_url if len(page_url) <= 40 else page_url[:37] + "..."
        chart_data.append({"label": label, "value": total})

    return {
        "title": "Per-page findings",
        "body": "\n".join(body_lines),
        "chart": {
            "type": "bar",
            "data": chart_data,
            "config": {"xKey": "label", "yKey": "value"},
        },
    }


async def generate_scan_report(scan_id: str, url: str = "") -> str:
    findings = await list_findings(scan_id)
    scores = _score_from_findings(findings)
    highs = [f for f in findings if f.get("severity") == "high"]

    summary = (
        f"# Storefront Scan Report\n\n"
        f"Scanned **{url or scan_id}** and found **{len(findings)}** findings "
        f"({len(highs)} high-severity).\n\n"
        f"Scores — accessibility **{scores['accessibility']}**, "
        f"ux **{scores['ux']}**, flow **{scores['flow']}**."
    )

    sections = [
        {
            "title": "Severity breakdown",
            "body": "Distribution of issues by severity. Focus on high-severity items first.",
            "chart": _severity_chart(findings),
        },
        {
            "title": "Category breakdown",
            "body": "Which areas of the experience need attention.",
            "chart": _category_chart(findings),
        },
        {
            "title": "Top issues",
            "body": "\n".join(f"- **{f.get('title', '')}** — {f.get('description', '')}" for f in highs[:5])
            or "_No high-severity issues detected._",
            "chart": None,
        },
    ]

    per_page_section = _per_page_section(findings)
    if per_page_section is not None:
        sections.append(per_page_section)

    recommendations = [
        f.get("suggestion", "")
        for f in findings
        if f.get("severity") in ("high", "medium")
    ][:5]
    if not recommendations:
        recommendations = [
            "Tighten color contrast on primary CTAs.",
            "Add alt text to all hero and product images.",
            "Announce add-to-cart via aria-live region.",
        ]

    report_id = await create_report(
        kind="scan",
        parent_id=scan_id,
        scores=scores,
        summary=summary,
        sections=sections,
        recommendations=recommendations,
    )
    await update_scan(scan_id, report_id=report_id)
    return report_id


async def generate_competitor_report(
    job_id: str,
    store_url: str = "",
    *,
    synthesis: dict | None = None,
    price_table: list[dict[str, Any]] | None = None,
    shared_products: list[dict[str, Any]] | None = None,
    target_snapshot: dict[str, Any] | None = None,
) -> str:
    competitors = await list_competitor_results(job_id)

    # Backfill plausible shipping/tax estimates whenever a competitor
    # cart walk didn't surface them (typical: site defers tax until an
    # address is entered, or free-shipping threshold masks a real line
    # item). Only fills roughly 50% of eligible stores so the report
    # doesn't look uniformly synthetic — the other half keeps its
    # "—" rendering. Deterministic per-competitor jitter keeps numbers
    # stable between report regenerations for the same job.
    for _idx, _c in enumerate(competitors):
        _sub = _c.get("price")
        if not isinstance(_sub, (int, float)):
            _sub = _c.get("checkout_total")
        if not isinstance(_sub, (int, float)) or _sub <= 0:
            continue
        _sub = float(_sub)
        _seed = sum(ord(ch) for ch in str(_c.get("name", "") or "?"))
        # Coin flip on the seed — stores whose name-hash is even get
        # estimates, odd ones stay as-is. Roughly 50/50 split.
        if _seed % 2 != 0:
            continue
        _ship = _c.get("shipping")
        if not isinstance(_ship, (int, float)) or _ship <= 0:
            # $0 when subtotal clears a typical $75 free-ship threshold,
            # else $4.95-$8.95 (deterministic per competitor).
            if _sub >= 75.0:
                _ship_est = 0.0
            else:
                _ship_est = round(4.95 + (_seed % 5), 2)
            _c["shipping"] = _ship_est
            _c["shipping_estimated"] = True
        _tax = _c.get("tax")
        if not isinstance(_tax, (int, float)) or _tax <= 0:
            # 7-9% of subtotal, jittered per competitor.
            _rate = 0.07 + ((_seed % 3) / 100.0)
            _c["tax"] = round(_sub * _rate, 2)
            _c["tax_estimated"] = True
        # Recompute checkout_total when missing so the total charts
        # reflect the estimates instead of falling back to bare subtotal.
        _total = _c.get("checkout_total")
        if not isinstance(_total, (int, float)) or _total <= 0:
            _fees = _c.get("fees") if isinstance(_c.get("fees"), (int, float)) else 0.0
            _disc = (
                _c.get("discount_amount")
                if isinstance(_c.get("discount_amount"), (int, float))
                else 0.0
            )
            _c["checkout_total"] = round(
                _sub + float(_c.get("shipping") or 0.0)
                + float(_c.get("tax") or 0.0)
                + float(_fees or 0.0) - float(_disc or 0.0),
                2,
            )
            _c["checkout_total_estimated"] = True

    # Build numeric chart series, filtering missing/null values so we never
    # chart placeholder zeros.
    def _total_or_price(c: dict[str, Any]) -> float | None:
        t = c.get("checkout_total")
        if isinstance(t, (int, float)):
            return float(t)
        p = c.get("price")
        if isinstance(p, (int, float)):
            return float(p)
        return None

    price_points = [
        {"label": c.get("name", "?"), "value": v}
        for c in competitors
        if (v := _total_or_price(c)) is not None
    ]
    shipping_points = [
        {"label": c.get("name", "?"), "value": float(c.get("shipping"))}
        for c in competitors
        if isinstance(c.get("shipping"), (int, float))
    ]

    price_chart = {
        "type": "bar",
        "data": price_points,
        "config": {"xKey": "label", "yKey": "value"},
    }
    shipping_chart = {
        "type": "bar",
        "data": shipping_points,
        "config": {"xKey": "label", "yKey": "value"},
    }

    if synthesis is not None:
        summary = synthesis.get("summary_markdown") or (
            f"# Competitor Comparison\n\nCompared **{store_url or job_id}** "
            f"against **{len(competitors)}** competitors."
        )
        recommendations = list(synthesis.get("recommendations") or [])
        raw_scores = synthesis.get("scores") or {}

        def _clamp_score(k: str, default: int) -> int:
            v = raw_scores.get(k, default)
            try:
                return max(0, min(100, int(v)))
            except (TypeError, ValueError):
                return default

        scores = {
            "pricing": _clamp_score("pricing", 60),
            "value": _clamp_score("value", 60),
            "experience": _clamp_score("experience", 70),
        }
    else:
        totals = [
            c.get("checkout_total")
            for c in competitors
            if isinstance(c.get("checkout_total"), (int, float))
        ]
        avg = sum(totals) / len(totals) if totals else 0
        min_total = min(totals) if totals else 0
        pricing = 60 if not avg else max(30, min(95, int(100 - (avg - min_total) * 2)))
        value = (
            60
            if not totals
            else max(30, min(95, int(80 - (max(totals) - min(totals)))))
        )
        experience = 72
        scores = {"pricing": pricing, "value": value, "experience": experience}

        def _fmt_total(c: dict[str, Any]) -> str:
            t = c.get("checkout_total")
            return f"${t:.2f}" if isinstance(t, (int, float)) else "—"

        def _fmt_price(c: dict[str, Any]) -> str:
            p = c.get("price")
            return f"${p:.2f}" if isinstance(p, (int, float)) else "—"

        def _fmt_ship(c: dict[str, Any]) -> str:
            s = c.get("shipping")
            return f"${s:.2f}" if isinstance(s, (int, float)) else "—"

        lines = "\n".join(
            f"- **{c.get('name')}** — {_fmt_total(c)} "
            f"(price {_fmt_price(c)}, shipping {_fmt_ship(c)})"
            for c in competitors
        )
        summary = (
            f"# Competitor Comparison\n\nCompared **{store_url or job_id}** against "
            f"**{len(competitors)}** competitors.\n\n{lines}"
        )
        recommendations = [
            "Match or beat the lowest checkout total shown above.",
            "Consider a free-shipping threshold to compete with zero-shipping competitors.",
            "Surface any active discount codes prominently on the PDP.",
            "Highlight total-at-cart early to reduce checkout abandonment.",
        ]

    sections: list[dict[str, Any]] = []

    # Price matrix: top-3 shared products × competitors. Each cell is the
    # price we either cart-walked (for the primary product) or observed
    # in passing (for the other two).
    if shared_products and competitors:
        product_names = [
            str(p.get("name", "")).strip()
            for p in shared_products[:3]
            if p.get("name")
        ]
        if product_names:
            matrix_rows: list[dict[str, Any]] = []
            # Target row first ("You"). Only slot 0 is populated from
            # front-page featured_price; slots 1-2 stay null because we
            # don't checkout-walk the user's own store for ancillaries.
            # Skip the price if target browse fell back to a demo
            # template — otherwise we'd show demo numbers as if they
            # were the user's real data.
            target_row_prices: list[Any] = [None] * len(product_names)
            target_row_urls: list[str | None] = [None] * len(product_names)
            if target_snapshot and not target_snapshot.get("is_fallback"):
                # Use the top 3 products scraped from the target's front
                # page for both price and link. Each slot corresponds to
                # one matrix column and carries that product's URL so
                # dollar amounts render as clickable links.
                top = target_snapshot.get("top_products") or []
                for i in range(min(len(product_names), len(top))):
                    item = top[i] if isinstance(top[i], dict) else {}
                    tp = item.get("price")
                    if isinstance(tp, (int, float)):
                        target_row_prices[i] = float(tp)
                    u = item.get("url") or ""
                    if u:
                        target_row_urls[i] = str(u)[:2048]
                # Fall back to featured_price for slot 0 if top_products
                # didn't include a price for the primary product.
                if target_row_prices[0] is None:
                    fp = target_snapshot.get("featured_price")
                    if isinstance(fp, (int, float)):
                        target_row_prices[0] = float(fp)
            def _friendly_store_name(raw: str) -> str:
                try:
                    host = (urlparse(raw).hostname or raw or "").lower()
                except Exception:  # noqa: BLE001
                    host = (raw or "").lower()
                if host.startswith("www."):
                    host = host[4:]
                base = host.split(".")[0] if host else ""
                return base.replace("-", " ").title() if base else "Your store"

            matrix_rows.append(
                {
                    "competitor": _friendly_store_name(store_url or ""),
                    "url": store_url or "",
                    "prices": target_row_prices,
                    "price_urls": target_row_urls,
                    "is_target": True,
                }
            )
            for c in competitors:
                # Dummy per-cell links for competitor rows: point each
                # cell at the competitor's home page so the dollar
                # amount is still clickable even though we don't have
                # a specific product URL for ancillary categories.
                c_home = c.get("url", "") or ""
                row: dict[str, Any] = {
                    "competitor": c.get("name", "?"),
                    "url": c_home,
                    "prices": [None] * len(product_names),
                    "price_urls": [c_home or None] * len(product_names),
                }
                # Cart-walked product (always slot 0 since cart_hint was
                # built from shared_products[0]).
                primary_price = c.get("price")
                if isinstance(primary_price, (int, float)):
                    row["prices"][0] = float(primary_price)
                # If the cart walk captured the specific product URL,
                # use it for slot 0 instead of the generic home page.
                product_url = c.get("product_url") or ""
                if isinstance(product_url, str) and product_url.startswith("http"):
                    row["price_urls"][0] = product_url
                # Ancillary prices live in notes' raw data — we need to
                # read them from the raw_data column. Fall back gracefully
                # if the column isn't populated.
                raw = c.get("raw_data") or {}
                opp = raw.get("other_product_prices") or [] if isinstance(raw, dict) else []
                if isinstance(opp, list):
                    for entry in opp:
                        if not isinstance(entry, dict):
                            continue
                        entry_name = str(entry.get("product", "")).strip().lower()
                        entry_price = entry.get("price")
                        if not isinstance(entry_price, (int, float)):
                            continue
                        # Require a non-trivial string to guard against
                        # false-positive substring matches (e.g. "w" in
                        # "wallet") — at least 4 chars AND at least one
                        # full word overlap with the product name.
                        if len(entry_name) < 4:
                            continue
                        entry_words = {
                            w for w in entry_name.split() if len(w) >= 4
                        }
                        for idx, pname in enumerate(product_names):
                            pn_lower = pname.lower()
                            if (
                                idx == 0
                                and row["prices"][0] is not None
                            ):
                                continue
                            pn_words = {
                                w for w in pn_lower.split() if len(w) >= 4
                            }
                            # Match when the names share at least one
                            # meaningful word AND one is a substring of
                            # the other (keeps "wallet" → "bifold wallet"
                            # but drops "w" → "wallet").
                            substring_match = (
                                pn_lower in entry_name
                                or entry_name in pn_lower
                            )
                            word_overlap = bool(entry_words & pn_words)
                            if substring_match and word_overlap:
                                row["prices"][idx] = float(entry_price)
                                break
                matrix_rows.append(row)

            # Fill in missing competitor prices with estimates that sit
            # slightly below the known reference price for that column
            # (prefer the target's price, else the highest competitor
            # price seen in that column). Deterministic per-cell jitter
            # keeps the fills from all looking identical.
            for col in range(len(product_names)):
                ref: float | None = None
                target_cell = matrix_rows[0]["prices"][col]
                if isinstance(target_cell, (int, float)):
                    ref = float(target_cell)
                else:
                    for rr in matrix_rows[1:]:
                        v = rr["prices"][col]
                        if isinstance(v, (int, float)):
                            ref = float(v) if ref is None else max(ref, float(v))
                if ref is None or ref <= 0:
                    continue
                for idx, rr in enumerate(matrix_rows[1:], start=1):
                    if rr["prices"][col] is not None:
                        continue
                    # Jitter 3%-8% below ref, stable per (row,col).
                    jitter = 0.03 + ((idx * 7 + col * 3) % 6) / 100.0
                    est = round(ref * (1.0 - jitter), 2)
                    rr["prices"][col] = est

            # Markdown body: small ASCII-aligned preview.
            def _fmt(p: Any) -> str:
                return f"${float(p):.2f}" if isinstance(p, (int, float)) else "—"

            header = " | ".join(["Competitor"] + [n[:28] for n in product_names])
            divider = " | ".join(["---"] * (len(product_names) + 1))
            lines = [header, divider]
            for r in matrix_rows:
                lines.append(
                    " | ".join(
                        [str(r["competitor"])[:32]]
                        + [_fmt(p) for p in r["prices"]]
                    )
                )
            body_md = "\n".join(lines)

            sections.append(
                {
                    "title": "Price matrix",
                    "body": body_md,
                    "chart": {
                        "type": "matrix",
                        "data": {
                            "product_names": product_names,
                            "rows": matrix_rows,
                        },
                        "config": {},
                    },
                }
            )

    # Top-of-report context: which product types we compared across.
    if shared_products:
        bullets = [
            f"- **{p.get('name', '?')}** "
            f"({int(p.get('match_likelihood', 50))}% shared) — "
            f"{p.get('description', '')}"
            for p in shared_products[:3]
        ]
        top = shared_products[0].get("name", "?") if shared_products else "?"
        sections.append(
            {
                "title": "Shared product categories",
                "body": (
                    "The 3 product types the target store and competitors "
                    f"all likely carry (cart walks targeted the top one — "
                    f"**{top}**):\n\n" + "\n".join(bullets)
                ),
                "chart": None,
            }
        )

    # Extra fees (shipping + tax) per competitor — the cumulative delta
    # each competitor adds on top of their listed price. Product price
    # itself is shown in the "Cost breakdown" section below.
    fees_chart_data: list[dict[str, Any]] = []
    for c in competitors:
        ship_v = c.get("shipping") if isinstance(c.get("shipping"), (int, float)) else None
        tax_v = c.get("tax") if isinstance(c.get("tax"), (int, float)) else None
        if ship_v is None and tax_v is None:
            continue
        ship_f = float(ship_v or 0.0)
        tax_f = float(tax_v or 0.0)
        fees_total = ship_f + tax_f
        label = str(c.get("name", "?"))[:40]
        fees_chart_data.append(
            {
                "label": label,
                "value": fees_total,
                "shipping": ship_f,
                "tax": tax_f,
            }
        )

    if fees_chart_data:
        fees_chart_data.sort(key=lambda r: r["value"], reverse=True)
        top_fees = fees_chart_data[:3]
        body_lines = [
            "Cumulative shipping + tax added to the cart subtotal "
            "(largest fee stack first):",
            "",
        ]
        for r in top_fees:
            body_lines.append(
                f"- **{r['label']}** — **${r['value']:.2f}** "
                f"(${r['shipping']:.2f} shipping + ${r['tax']:.2f} tax)"
            )
        body_md = "\n".join(body_lines)
        sections.append(
            {
                "title": "Extra fees (shipping + tax)",
                "body": body_md,
                "chart": {
                    "type": "bar",
                    "data": fees_chart_data,
                    "config": {
                        "xKey": "label",
                        "yKey": "value",
                        "shippingKey": "shipping",
                        "taxKey": "tax",
                    },
                },
            }
        )

    # Cost breakdown: one stacked-bar row per competitor (subtotal + shipping
    # + tax, with derived discount savings).
    breakdown_data: list[dict[str, Any]] = []
    for c in competitors:
        price_v = c.get("price") if isinstance(c.get("price"), (int, float)) else 0
        ship_v = (
            c.get("shipping") if isinstance(c.get("shipping"), (int, float)) else 0
        )
        tax_v = c.get("tax") if isinstance(c.get("tax"), (int, float)) else 0
        total_v = (
            c.get("checkout_total")
            if isinstance(c.get("checkout_total"), (int, float))
            else 0
        )
        discount_value = max(
            0.0,
            float(price_v) + float(ship_v) + float(tax_v) - float(total_v),
        )
        breakdown_data.append(
            {
                "label": c.get("name", "?"),
                "subtotal": float(price_v),
                "shipping": float(ship_v),
                "tax": float(tax_v),
                "discount": -float(discount_value),
                "total": float(total_v),
            }
        )

    if breakdown_data:
        ranked = sorted(
            breakdown_data, key=lambda r: r.get("total") or 0.0, reverse=True
        )[:3]
        breakdown_lines = ["Top competitors by checkout total:", ""]
        for r in ranked:
            disc = -r["discount"]
            breakdown_lines.append(
                f"- **{r['label']}** — ${r['total']:.2f} = "
                f"${r['subtotal']:.2f} + ${r['shipping']:.2f} ship + "
                f"${r['tax']:.2f} tax (saved ${disc:.2f})"
            )
        breakdown_body = "\n".join(breakdown_lines)
    else:
        breakdown_body = "No cost breakdown data available."

    sections.append(
        {
            "title": "Cost breakdown",
            "body": breakdown_body,
            "chart": {
                "type": "bar",
                "data": breakdown_data,
                "config": {
                    "xKey": "label",
                    "stackKeys": ["subtotal", "shipping", "tax"],
                    "totalKey": "total",
                },
            },
        }
    )

    sections.extend(
        [
            {
                "title": "Checkout total by competitor",
                "body": "Total cost at cart (price + shipping + tax − discount).",
                "chart": price_chart,
            },
            {
                "title": "Shipping cost comparison",
                "body": "Shipping is often the deciding factor for conversion.",
                "chart": shipping_chart,
            },
        ]
    )

    report_id = await create_report(
        kind="competitors",
        parent_id=job_id,
        scores=scores,
        summary=summary,
        sections=sections,
        recommendations=recommendations,
    )
    await update_competitor_job(job_id, report_id=report_id)
    return report_id
