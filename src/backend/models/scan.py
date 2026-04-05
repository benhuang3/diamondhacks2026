from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from datetime import datetime

from ..security.url_guard import UnsafeURLError, validate_public_url

Severity = Literal["high", "medium", "low"]
Category = Literal["a11y", "ux", "contrast", "nav"]
Status = Literal["pending", "running", "done", "failed"]


class ScanRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    max_pages: int = Field(5, ge=1, le=50)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        try:
            return validate_public_url(v)
        except UnsafeURLError as e:
            raise ValueError(str(e)) from e


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


class ScanStep(BaseModel):
    step: int
    ts: float = 0.0
    source: str = "worker"  # "worker" | "claude" | "browser-use"
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""
    actions: list[str] = []


class ScanStatus(BaseModel):
    scan_id: str
    status: Status
    progress: float = 0.0
    url: str
    findings_count: int = 0
    report_id: Optional[str] = None
    error: Optional[str] = None
    steps: list[ScanStep] = []


class AnnotationsResponse(BaseModel):
    scan_id: str
    url: str
    annotations: list[ScanFinding]


class ScanSummary(BaseModel):
    scan_id: str
    url: str
    status: Status
    progress: float = 0.0
    findings_count: int = 0
    report_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ScanListResponse(BaseModel):
    scans: list[ScanSummary]
