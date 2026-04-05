"""Scan endpoints: POST /scan, GET /scan/{id}."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from ..models.scan import ScanCreateResponse, ScanRequest, ScanStatus
from ..services.scan_service import fetch_scan_status, start_scan
from ..workers.scan_worker import run_scan

router = APIRouter(tags=["scan"])


@router.post("/scan", response_model=ScanCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scan_endpoint(
    req: ScanRequest, background_tasks: BackgroundTasks
) -> ScanCreateResponse:
    scan_id = await start_scan(req.url, req.max_pages)
    background_tasks.add_task(run_scan, scan_id, req.url, req.max_pages)
    return ScanCreateResponse(scan_id=scan_id, status="pending")


@router.get("/scan/{scan_id}", response_model=ScanStatus)
async def get_scan_endpoint(scan_id: str) -> ScanStatus:
    s = await fetch_scan_status(scan_id)
    if not s:
        raise HTTPException(status_code=404, detail="scan not found")
    return s
