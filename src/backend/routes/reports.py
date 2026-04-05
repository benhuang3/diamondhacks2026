"""Report endpoint: GET /report/{id}."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.db.queries import get_report

from ..models.report import Report, ReportSection

router = APIRouter(tags=["reports"])


def _sections_from_raw(raw: Any) -> list[ReportSection]:
    if not raw:
        return []
    out: list[ReportSection] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(ReportSection(**item))
            except Exception:  # noqa: BLE001
                out.append(
                    ReportSection(
                        title=str(item.get("title", "")),
                        body=str(item.get("body", "")),
                        chart=item.get("chart"),
                    )
                )
    return out


@router.get("/report/{report_id}", response_model=Report)
async def get_report_endpoint(report_id: str) -> Report:
    row = await get_report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return Report(
        report_id=str(row.get("id") or row.get("report_id") or report_id),
        kind=row.get("kind", "scan"),
        parent_id=str(row.get("parent_id", "")),
        scores=row.get("scores") or {},
        summary=row.get("summary", ""),
        sections=_sections_from_raw(row.get("sections")),
        recommendations=row.get("recommendations") or [],
    )
