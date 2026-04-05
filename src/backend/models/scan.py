from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from datetime import datetime

from ..security.url_guard import UnsafeURLError, validate_public_url

Severity = Literal["high", "medium", "low"]
Category = Literal["a11y", "ux", "contrast", "nav"]
Status = Literal["pending", "running", "done", "failed", "cancelled"]


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
    # Groups entries into separate UI panels. Empty string goes to the
    # main panel. Used to show each parallel agent in its own window.
    lane: str = ""
    # Live-session URL from browser-use cloud. Populated on the first
    # step of a cloud task so the UI can render a "watch live" link per
    # lane. Empty/None everywhere else.
    live_url: str = ""
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


# --- Fix operations -------------------------------------------------------

FixKind = Literal["css", "attribute", "class", "none"]


class FixOperation(BaseModel):
    """A single DOM-mutation operation that safely fixes one finding.

    Validated by :func:`fix_validator.validate_fix_operation` before it
    ever reaches the extension — callers can treat any instance returned
    from the API as already-safe for direct application.
    """

    kind: FixKind
    # css kind
    rules: Optional[str] = None
    # attribute / class kinds
    selector: Optional[str] = None
    # attribute kind
    name: Optional[str] = None
    value: Optional[str] = None
    # class kind (space-separated token list)
    classes: Optional[str] = None
    # none kind (plus human explanation on any kind if helpful)
    reason: Optional[str] = None


class FixResponse(BaseModel):
    finding_id: str
    operation: FixOperation
