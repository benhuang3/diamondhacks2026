"""Scan business logic: create, fetch status, list annotations."""

from __future__ import annotations

from typing import Optional

from src.db.queries import (
    count_findings,
    create_scan,
    get_scan,
    list_findings,
    list_scans,
)

from ..models.scan import (
    AnnotationsResponse,
    BoundingBox,
    ScanFinding,
    ScanStatus,
    ScanStep,
    ScanSummary,
)
from ..observability import scan_log


async def start_scan(url: str, max_pages: int) -> str:
    return await create_scan(url, max_pages)


async def fetch_scan_status(scan_id: str) -> Optional[ScanStatus]:
    row = await get_scan(scan_id)
    if not row:
        return None
    findings_count = await count_findings(scan_id)
    steps = [ScanStep(**e) for e in scan_log.snapshot(scan_id)]
    return ScanStatus(
        scan_id=str(row.get("id") or row.get("scan_id") or scan_id),
        status=row.get("status", "pending"),
        progress=float(row.get("progress") or 0.0),
        url=row.get("url", ""),
        findings_count=findings_count,
        report_id=(str(row["report_id"]) if row.get("report_id") else None),
        error=row.get("error"),
        steps=steps,
    )


def _finding_from_row(row: dict, scan_id: str) -> ScanFinding:
    bbox_raw = row.get("bounding_box")
    bbox: Optional[BoundingBox] = None
    if isinstance(bbox_raw, dict):
        try:
            bbox = BoundingBox(**bbox_raw)
        except Exception:  # noqa: BLE001
            bbox = None
    return ScanFinding(
        id=str(row.get("id")),
        scan_id=str(row.get("scan_id") or scan_id),
        selector=row.get("selector", "body"),
        xpath=row.get("xpath"),
        bounding_box=bbox,
        severity=row.get("severity", "medium"),
        category=row.get("category", "ux"),
        title=row.get("title", ""),
        description=row.get("description", ""),
        suggestion=row.get("suggestion", ""),
        page_url=row.get("page_url", ""),
    )


async def fetch_scan_list(limit: int = 50) -> list[ScanSummary]:
    rows = await list_scans(limit=limit)
    return [
        ScanSummary(
            scan_id=str(r.get("id") or r.get("scan_id")),
            url=r.get("url", ""),
            status=r.get("status", "pending"),
            progress=float(r.get("progress") or 0.0),
            findings_count=int(r.get("findings_count") or 0),
            report_id=(str(r["report_id"]) if r.get("report_id") else None),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


async def fetch_annotations(scan_id: str) -> Optional[AnnotationsResponse]:
    scan = await get_scan(scan_id)
    if not scan:
        return None
    rows = await list_findings(scan_id)
    findings = [_finding_from_row(r, scan_id) for r in rows]
    return AnnotationsResponse(
        scan_id=scan_id,
        url=scan.get("url", ""),
        annotations=findings,
    )
