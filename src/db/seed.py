"""Seed demo data for offline demo / Phase 3 integration.

Idempotent: if any scan already exists, seeding is skipped.
"""

from __future__ import annotations

from sqlalchemy import select

from src.db.client import AsyncSessionLocal
from src.db.queries import (
    create_competitor_job,
    create_report,
    create_scan,
    insert_competitor_result,
    insert_finding,
    update_competitor_job,
    update_scan,
)
from src.db.schema import Scan


async def _already_seeded() -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Scan.id).limit(1))
        return result.first() is not None


async def seed_demo_data() -> None:
    """Insert: 1 scan + 3 findings + 1 competitor job + 3 results + 2 reports.

    Safe to call at startup — returns immediately if data exists.
    """
    if await _already_seeded():
        return

    demo_url = "https://demo-store.example.com"

    # --- Scan + findings -----------------------------------------------------
    scan_id = await create_scan(demo_url, max_pages=3)

    findings = [
        {
            "selector": "button.checkout",
            "xpath": "/html/body/main/div[2]/button",
            "bounding_box": {"x": 320.0, "y": 560.0, "w": 180.0, "h": 44.0},
            "severity": "high",
            "category": "contrast",
            "title": "Low contrast checkout button",
            "description": (
                "The primary checkout CTA has a contrast ratio of 2.8:1 against "
                "its background, below WCAG AA minimum of 4.5:1 for normal text."
            ),
            "suggestion": (
                "Darken button background to #1E40AF or lighten text to #FFFFFF "
                "to reach at least 4.5:1 contrast ratio."
            ),
            "page_url": demo_url,
        },
        {
            "selector": "img.product-hero",
            "xpath": "/html/body/main/section[1]/img",
            "bounding_box": {"x": 40.0, "y": 120.0, "w": 600.0, "h": 400.0},
            "severity": "medium",
            "category": "a11y",
            "title": "Hero image missing alt text",
            "description": (
                "Product hero image has no alt attribute, making it invisible "
                "to screen readers and hurting SEO."
            ),
            "suggestion": (
                "Add descriptive alt text such as alt=\"Blue running shoe, "
                "side view\"."
            ),
            "page_url": demo_url,
        },
        {
            "selector": "nav .menu-toggle",
            "xpath": "/html/body/header/nav/button",
            "bounding_box": {"x": 16.0, "y": 16.0, "w": 40.0, "h": 40.0},
            "severity": "low",
            "category": "nav",
            "title": "Mobile menu lacks aria-expanded state",
            "description": (
                "Hamburger toggle does not expose aria-expanded, so assistive "
                "tech cannot announce open/closed state."
            ),
            "suggestion": (
                "Add aria-expanded=\"false\" by default and toggle to \"true\" "
                "when the menu opens."
            ),
            "page_url": demo_url,
        },
    ]
    for f in findings:
        await insert_finding(scan_id, f)

    # --- Scan report ---------------------------------------------------------
    scan_report_id = await create_report(
        kind="scan",
        parent_id=scan_id,
        scores={"accessibility": 72, "ux": 65, "flow": 80},
        summary=(
            "## Storefront Audit Summary\n\n"
            "Overall the storefront is functional but shows three notable "
            "accessibility and contrast issues that hurt conversion on mobile."
        ),
        sections=[
            {
                "title": "Accessibility",
                "body": (
                    "Two a11y violations detected. Missing alt text and "
                    "aria-expanded are easy fixes with high impact."
                ),
                "chart": {
                    "type": "bar",
                    "data": [
                        {"name": "a11y", "value": 2},
                        {"name": "contrast", "value": 1},
                        {"name": "nav", "value": 1},
                    ],
                    "config": {"color": "#3B82F6"},
                },
            },
            {
                "title": "Visual Design",
                "body": "Contrast ratios below WCAG AA on primary CTA.",
                "chart": None,
            },
        ],
        recommendations=[
            "Fix checkout button contrast to meet WCAG AA (4.5:1).",
            "Add alt text to all product images.",
            "Expose aria-expanded on mobile nav toggle.",
        ],
    )
    await update_scan(scan_id, status="done", progress=1.0, report_id=scan_report_id)

    # --- Competitor job + results -------------------------------------------
    job_id = await create_competitor_job(
        store_url=demo_url,
        custom_prompt="Compare pricing on blue running shoes size 10",
        product_hint="blue running shoes",
    )

    competitors = [
        {
            "name": "SwiftStride",
            "url": "https://swiftstride.example.com/blue-runner-10",
            "price": 89.99,
            "shipping": 5.99,
            "tax": 7.20,
            "discount": "SPRING10",
            "checkout_total": 94.18,
            "raw_data": {"currency": "USD", "in_stock": True},
            "notes": "Applied SPRING10 code; free return shipping.",
        },
        {
            "name": "PaceCraft",
            "url": "https://pacecraft.example.com/runners/blue-10",
            "price": 94.50,
            "shipping": 0.0,
            "tax": 7.56,
            "discount": None,
            "checkout_total": 102.06,
            "raw_data": {"currency": "USD", "in_stock": True},
            "notes": "Free shipping over $75; no active promo.",
        },
        {
            "name": "TrailKicks",
            "url": "https://trailkicks.example.com/shop/blue-runner",
            "price": 79.00,
            "shipping": 8.50,
            "tax": 6.32,
            "discount": "FIRST5",
            "checkout_total": 89.82,
            "raw_data": {"currency": "USD", "in_stock": False},
            "notes": "Out of stock in size 10; backorder 2 weeks.",
        },
    ]
    for c in competitors:
        await insert_competitor_result(job_id, c)

    # --- Competitor report ---------------------------------------------------
    comp_report_id = await create_report(
        kind="competitors",
        parent_id=job_id,
        scores={"pricing": 68, "value": 74, "experience": 81},
        summary=(
            "## Competitor Pricing Analysis\n\n"
            "Your storefront's checkout total is 6% higher than the market "
            "median, driven primarily by shipping costs."
        ),
        sections=[
            {
                "title": "Price Deltas",
                "body": "TrailKicks is the cheapest but out of stock.",
                "chart": {
                    "type": "bar",
                    "data": [
                        {"name": "SwiftStride", "value": 94.18},
                        {"name": "PaceCraft", "value": 102.06},
                        {"name": "TrailKicks", "value": 89.82},
                    ],
                    "config": {"color": "#10B981"},
                },
            },
        ],
        recommendations=[
            "Offer free shipping threshold at $75 to match PaceCraft.",
            "Run a first-time-buyer promo code to compete with TrailKicks.",
            "Highlight in-stock status to capture TrailKicks' lost sales.",
        ],
    )
    await update_competitor_job(
        job_id, status="done", progress=1.0, report_id=comp_report_id
    )
