"""Report generation for scans and competitor jobs.

DEMO_MODE produces deterministic canned content. Live mode asks Claude for a
summary + sections, but falls back to demo output on failure.
"""

from __future__ import annotations

import logging
from typing import Any

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
) -> str:
    competitors = await list_competitor_results(job_id)

    # Build numeric chart series, filtering missing/null values so we never
    # chart placeholder zeros.
    price_points = [
        {"label": c.get("name", "?"), "value": float(c.get("checkout_total"))}
        for c in competitors
        if isinstance(c.get("checkout_total"), (int, float))
    ]
    # If checkout_total isn't populated (new text-only snapshot pipeline),
    # fall back to featured price so the chart still has something useful.
    if not price_points:
        price_points = [
            {"label": c.get("name", "?"), "value": float(c.get("price"))}
            for c in competitors
            if isinstance(c.get("price"), (int, float))
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

    # Per-product price breakdown — biggest |delta vs. your store| first.
    if price_table:
        pt_chart_data: list[dict[str, Any]] = []
        for row in price_table:
            if not isinstance(row.get("price"), (int, float)):
                continue
            label = f"{row.get('store', '?')}: {row.get('product', '') or '(unnamed)'}"
            if len(label) > 60:
                label = label[:57] + "…"
            pt_chart_data.append(
                {
                    "label": label,
                    "value": float(row["price"]),
                    "delta": (
                        float(row["delta_vs_target"])
                        if isinstance(row.get("delta_vs_target"), (int, float))
                        else None
                    ),
                    "is_target": bool(row.get("is_target")),
                }
            )

        # Build a readable markdown body summarizing the biggest gaps.
        deltas = [
            r for r in price_table
            if not r.get("is_target")
            and isinstance(r.get("delta_vs_target"), (int, float))
        ]
        if deltas:
            top = deltas[:3]
            body_lines = [
                "Biggest per-product price gaps vs. your featured product:",
                "",
            ]
            for r in top:
                d = r["delta_vs_target"]
                arrow = "▲" if d > 0 else "▼"
                body_lines.append(
                    f"- {arrow} **${abs(d):.2f}** "
                    f"— {r['store']} {r.get('product') or '(unnamed)'} "
                    f"@ ${r['price']:.2f}"
                )
            body_md = "\n".join(body_lines)
        else:
            body_md = (
                "Showing per-product featured prices. Your store's "
                "featured_price wasn't captured, so deltas aren't shown."
            )

        sections.append(
            {
                "title": "Price breakdown by product",
                "body": body_md,
                "chart": {
                    "type": "bar",
                    "data": pt_chart_data,
                    "config": {
                        "xKey": "label",
                        "yKey": "value",
                        "deltaKey": "delta",
                        "targetKey": "is_target",
                    },
                },
            }
        )

    sections.extend(
        [
            {
                "title": "Checkout total comparison",
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
