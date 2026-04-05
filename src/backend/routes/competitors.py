"""Competitor endpoints: POST /competitors, GET /competitors/{id}."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from ..models.competitor import (
    CompetitorCreateResponse,
    CompetitorJobStatus,
    CompetitorRequest,
)
from ..services.competitor_service import fetch_competitor_job, start_competitor_job
from ..workers.competitor_worker import run_competitor_job

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


@router.get("/competitors/{job_id}", response_model=CompetitorJobStatus)
async def get_competitor_endpoint(job_id: str) -> CompetitorJobStatus:
    s = await fetch_competitor_job(job_id)
    if not s:
        raise HTTPException(status_code=404, detail="competitor job not found")
    return s
