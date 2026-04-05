"""Pydantic models for the backend API."""

from .scan import (
    AnnotationsResponse,
    BoundingBox,
    Category,
    ScanCreateResponse,
    ScanFinding,
    ScanRequest,
    ScanStatus,
    Severity,
    Status,
)
from .competitor import (
    CompetitorCreateResponse,
    CompetitorJobStatus,
    CompetitorRequest,
    CompetitorResult,
)
from .report import Report, ReportSection

__all__ = [
    "AnnotationsResponse",
    "BoundingBox",
    "Category",
    "CompetitorCreateResponse",
    "CompetitorJobStatus",
    "CompetitorRequest",
    "CompetitorResult",
    "Report",
    "ReportSection",
    "ScanCreateResponse",
    "ScanFinding",
    "ScanRequest",
    "ScanStatus",
    "Severity",
    "Status",
]
