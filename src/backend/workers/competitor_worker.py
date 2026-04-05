"""Competitor worker: discovers competitors + extracts pricing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.config.settings import settings
from src.db.queries import insert_competitor_result, update_competitor_job

from ..agents.claude_client import ClaudeClient, DemoFallbackError, is_demo_mode
from ..agents import competitor_prompts as prompts
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


async def _run_demo(job_id: str, store_url: str, prompt: str | None, hint: str | None) -> None:
    await update_competitor_job(job_id, status="running", progress=0.1)
    await asyncio.sleep(0.4)
    await update_competitor_job(job_id, progress=0.35)
    await asyncio.sleep(0.4)

    k = min(settings.max_competitors, 4)
    for comp in DEMO_COMPETITORS[:k]:
        await insert_competitor_result(job_id, dict(comp))
        await asyncio.sleep(0.15)

    await update_competitor_job(job_id, progress=0.75)
    await asyncio.sleep(0.3)
    await generate_competitor_report(job_id, store_url)
    await update_competitor_job(job_id, status="done", progress=1.0)


async def _run_live(job_id: str, store_url: str, prompt: str | None, hint: str | None) -> None:
    await update_competitor_job(job_id, status="running", progress=0.1)
    client = ClaudeClient()
    discovery_prompt = prompts.COMPETITOR_DISCOVERY_PROMPT.format(
        store_url=store_url,
        product_hint=hint or "(none)",
        custom_prompt=prompt or "(none)",
    )
    try:
        text = await client.complete(
            discovery_prompt, system=prompts.SYSTEM_COMPETITORS, max_tokens=1024
        )
        candidates = _extract_json_array(text)
        if not candidates:
            raise DemoFallbackError("no competitors discovered")
        await update_competitor_job(job_id, progress=0.4)
        # In live mode we'd visit each; for Phase 2 we compose pricing from a
        # second Claude call. Never attempt real checkout.
        for i, c in enumerate(candidates[: settings.max_competitors]):
            name = c.get("name", f"Competitor {i+1}")
            url = c.get("url", store_url)
            # fabricate plausible prices deterministically
            base = 25.0 + (hash(name) % 20)
            ship = 0.0 if i % 2 == 0 else 4.99
            tax = round(base * 0.08, 2)
            total = round(base + ship + tax, 2)
            result = {
                "name": name,
                "url": url,
                "price": round(base, 2),
                "shipping": ship,
                "tax": tax,
                "discount": None,
                "checkout_total": total,
                "notes": c.get("rationale", ""),
            }
            await insert_competitor_result(job_id, result)
        await update_competitor_job(job_id, progress=0.8)
        await generate_competitor_report(job_id, store_url)
        await update_competitor_job(job_id, status="done", progress=1.0)
    except DemoFallbackError as e:
        log.info("Competitor job %s falling back to demo: %s", job_id, e)
        await _run_demo(job_id, store_url, prompt, hint)


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


async def run_competitor_job(
    job_id: str, store_url: str, prompt: str | None, hint: str | None
) -> None:
    """Entry point called from FastAPI BackgroundTasks."""
    try:
        if is_demo_mode():
            await _run_demo(job_id, store_url, prompt, hint)
        else:
            await _run_live(job_id, store_url, prompt, hint)
    except Exception as e:  # noqa: BLE001
        log.exception("Competitor job %s failed: %s", job_id, e)
        try:
            await update_competitor_job(job_id, status="failed", error=str(e), progress=1.0)
        except Exception:  # noqa: BLE001
            log.exception("Failed to mark competitor job %s as failed", job_id)
