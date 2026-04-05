"""Annotations endpoint used by the Chrome extension."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.scan import AnnotationsResponse
from ..services.scan_service import fetch_annotations

router = APIRouter(tags=["annotations"])


@router.get("/annotations/{scan_id}", response_model=AnnotationsResponse)
async def get_annotations_endpoint(scan_id: str) -> AnnotationsResponse:
    r = await fetch_annotations(scan_id)
    if r is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return r
