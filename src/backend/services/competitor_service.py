"""Competitor business logic."""

from __future__ import annotations

from typing import Optional

from src.db.queries import (
    create_competitor_job,
    get_competitor_job,
    list_competitor_results,
    update_competitor_job,
)

from ..models.competitor import CompetitorJobStatus, CompetitorResult
from ..models.scan import ScanStep
from ..observability import cancellation, scan_log


_TERMINAL_STATUSES = {"done", "failed", "cancelled"}


async def start_competitor_job(
    store_url: str, custom_prompt: Optional[str], product_hint: Optional[str]
) -> str:
    return await create_competitor_job(store_url, custom_prompt, product_hint)


def _result_from_row(row: dict, job_id: str) -> CompetitorResult:
    # shipping_days isn't a dedicated column — it rides in raw_data JSON.
    raw = row.get("raw_data") or {}
    shipping_days = raw.get("shipping_days") if isinstance(raw, dict) else None
    if shipping_days is not None:
        try:
            shipping_days = int(shipping_days)
        except (TypeError, ValueError):
            shipping_days = None
    return CompetitorResult(
        id=str(row.get("id")),
        job_id=str(row.get("job_id") or job_id),
        name=row.get("name", ""),
        url=row.get("url", ""),
        price=row.get("price"),
        shipping=row.get("shipping"),
        tax=row.get("tax"),
        discount=row.get("discount"),
        checkout_total=row.get("checkout_total"),
        shipping_days=shipping_days,
        notes=row.get("notes") or "",
    )


async def cancel_competitor_job(job_id: str) -> Optional[CompetitorJobStatus]:
    """Mark a competitor job as cancelled. Returns the updated status,
    or None if the job doesn't exist. No-op if the job is already in a
    terminal state."""
    job = await get_competitor_job(job_id)
    if not job:
        return None
    current = job.get("status", "pending")
    if current in _TERMINAL_STATUSES:
        # Already terminal — don't overwrite.
        return await fetch_competitor_job(job_id)
    cancellation.mark_cancelled(job_id)
    await update_competitor_job(
        job_id,
        status="cancelled",
        error="cancelled by user",
        progress=1.0,
    )
    return await fetch_competitor_job(job_id)


async def fetch_competitor_job(job_id: str) -> Optional[CompetitorJobStatus]:
    job = await get_competitor_job(job_id)
    if not job:
        return None
    rows = await list_competitor_results(job_id)
    results = [_result_from_row(r, job_id) for r in rows]
    steps = [ScanStep(**e) for e in scan_log.snapshot(job_id)]
    return CompetitorJobStatus(
        job_id=str(job.get("id") or job.get("job_id") or job_id),
        status=job.get("status", "pending"),
        progress=float(job.get("progress") or 0.0),
        store_url=job.get("store_url", ""),
        competitors=results,
        report_id=(str(job["report_id"]) if job.get("report_id") else None),
        error=job.get("error"),
        steps=steps,
    )
