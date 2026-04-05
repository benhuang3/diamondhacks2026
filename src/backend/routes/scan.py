"""Scan endpoints: POST /scan, GET /scan/{id}, POST /scan/{id}/findings/{id}/fix."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from ..models.scan import (
    FixResponse,
    ScanCreateResponse,
    ScanListResponse,
    ScanRequest,
    ScanStatus,
)
from ..services.scan_service import (
    FindingNotFoundError,
    FixRateLimitError,
    fetch_scan_list,
    fetch_scan_status,
    generate_finding_fix,
    start_scan,
)
from ..workers.scan_worker import run_scan

router = APIRouter(tags=["scan"])


@router.post("/scan", response_model=ScanCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scan_endpoint(
    req: ScanRequest, background_tasks: BackgroundTasks
) -> ScanCreateResponse:
    scan_id = await start_scan(req.url, req.max_pages)
    background_tasks.add_task(run_scan, scan_id, req.url, req.max_pages)
    return ScanCreateResponse(scan_id=scan_id, status="pending")


@router.get("/scans", response_model=ScanListResponse)
async def list_scans_endpoint(
    limit: int = Query(50, ge=1, le=200),
) -> ScanListResponse:
    scans = await fetch_scan_list(limit=limit)
    return ScanListResponse(scans=scans)


@router.get("/scan/{scan_id}", response_model=ScanStatus)
async def get_scan_endpoint(scan_id: str) -> ScanStatus:
    s = await fetch_scan_status(scan_id)
    if not s:
        raise HTTPException(status_code=404, detail="scan not found")
    return s


@router.post(
    "/scan/{scan_id}/findings/{finding_id}/fix",
    response_model=FixResponse,
)
async def generate_finding_fix_endpoint(
    scan_id: str, finding_id: str
) -> FixResponse:
    try:
        op = await generate_finding_fix(scan_id, finding_id)
    except FindingNotFoundError:
        raise HTTPException(status_code=404, detail="finding not found")
    except FixRateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail="fix rate limit exceeded for this scan",
            headers={"Retry-After": str(e.retry_after)},
        )
    return FixResponse(finding_id=finding_id, operation=op)
