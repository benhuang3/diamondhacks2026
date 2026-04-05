"""Competitor endpoints: POST /competitors, GET /competitors/{id}."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from ..models.competitor import (
    CompetitorCreateResponse,
    CompetitorJobListResponse,
    CompetitorJobStatus,
    CompetitorJobSummary,
    CompetitorRequest,
)
from ..services.competitor_service import (
    cancel_competitor_job,
    fetch_competitor_job,
    start_competitor_job,
)
from ..workers.competitor_worker import run_competitor_job
from src.db.queries import list_competitor_jobs

router = APIRouter(tags=["competitors"])


@router.post(
    "/competitors",
    response_model=CompetitorCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_competitor_endpoint(
    req: CompetitorRequest, background_tasks: BackgroundTasks
) -> CompetitorCreateResponse:
    job_id = await start_competitor_job(req.store_url, req.custom_prompt, req.product_hint)
    background_tasks.add_task(
        run_competitor_job, job_id, req.store_url, req.custom_prompt, req.product_hint
    )
    return CompetitorCreateResponse(job_id=job_id, status="pending")


@router.get("/competitors", response_model=CompetitorJobListResponse)
async def list_competitor_endpoint(limit: int = 50) -> CompetitorJobListResponse:
    limit = max(1, min(int(limit or 50), 200))
    jobs = await list_competitor_jobs(limit=limit)
    summaries: list[CompetitorJobSummary] = []
    for j in jobs:
        created = j.get("created_at")
        updated = j.get("updated_at")
        summaries.append(
            CompetitorJobSummary(
                job_id=j.get("id", ""),
                status=j.get("status", "pending"),
                progress=float(j.get("progress") or 0.0),
                store_url=j.get("store_url", "") or "",
                report_id=j.get("report_id"),
                created_at=created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                updated_at=updated.isoformat() if hasattr(updated, "isoformat") else str(updated or ""),
            )
        )
    return CompetitorJobListResponse(jobs=summaries)


@router.get("/competitors/{job_id}", response_model=CompetitorJobStatus)
async def get_competitor_endpoint(job_id: str) -> CompetitorJobStatus:
    s = await fetch_competitor_job(job_id)
    if not s:
        raise HTTPException(status_code=404, detail="competitor job not found")
    return s


@router.post("/competitors/{job_id}/cancel", response_model=CompetitorJobStatus)
async def cancel_competitor_endpoint(job_id: str) -> CompetitorJobStatus:
    s = await cancel_competitor_job(job_id)
    if not s:
        raise HTTPException(status_code=404, detail="competitor job not found")
    return s
