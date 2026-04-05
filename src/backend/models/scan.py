from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime

Severity = Literal["high", "medium", "low"]
Category = Literal["a11y", "ux", "contrast", "nav"]
Status = Literal["pending", "running", "done", "failed"]


class ScanRequest(BaseModel):
    url: str
    max_pages: int = 5


class ScanCreateResponse(BaseModel):
    scan_id: str
    status: Status


class BoundingBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ScanFinding(BaseModel):
    id: str
    scan_id: str
    selector: str
    xpath: Optional[str] = None
    bounding_box: Optional[BoundingBox] = None
    severity: Severity
    category: Category
    title: str
    description: str
    suggestion: str
    page_url: str


class ScanStatus(BaseModel):
    scan_id: str
    status: Status
    progress: float = 0.0
    url: str
    findings_count: int = 0
    report_id: Optional[str] = None
    error: Optional[str] = None


class AnnotationsResponse(BaseModel):
    scan_id: str
    url: str
    annotations: list[ScanFinding]
