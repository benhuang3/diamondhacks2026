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


async def generate_competitor_report(job_id: str, store_url: str = "") -> str:
    competitors = await list_competitor_results(job_id)

    # scores: pricing = inverse of avg total; value = spread; experience = canned
    totals = [c.get("checkout_total") or 0 for c in competitors if c.get("checkout_total")]
    avg = sum(totals) / len(totals) if totals else 0
    min_total = min(totals) if totals else 0
    pricing = 60 if not avg else max(30, min(95, int(100 - (avg - min_total) * 2)))
    value = 60 if not totals else max(30, min(95, int(80 - (max(totals) - min(totals)))))
    experience = 72

    scores = {"pricing": pricing, "value": value, "experience": experience}

    lines = "\n".join(
        f"- **{c.get('name')}** — ${c.get('checkout_total', 0):.2f} "
        f"(price ${c.get('price', 0):.2f}, shipping ${c.get('shipping', 0):.2f})"
        for c in competitors
    )
    summary = (
        f"# Competitor Comparison\n\nCompared **{store_url or job_id}** against "
        f"**{len(competitors)}** competitors.\n\n{lines}"
    )

    price_chart = {
        "type": "bar",
        "data": [
            {"label": c.get("name", "?"), "value": c.get("checkout_total") or 0}
            for c in competitors
        ],
        "config": {"xKey": "label", "yKey": "value"},
    }
    shipping_chart = {
        "type": "bar",
        "data": [
            {"label": c.get("name", "?"), "value": c.get("shipping") or 0}
            for c in competitors
        ],
        "config": {"xKey": "label", "yKey": "value"},
    }

    sections = [
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

    recommendations = [
        "Match or beat the lowest checkout total shown above.",
        "Consider a free-shipping threshold to compete with zero-shipping competitors.",
        "Surface any active discount codes prominently on the PDP.",
        "Highlight total-at-cart early to reduce checkout abandonment.",
    ]

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
