from pydantic import BaseModel
from typing import Literal, Optional, Any


class ReportSection(BaseModel):
    title: str
    body: str  # markdown
    chart: Optional[dict[str, Any]] = None  # {type, data, config}


class Report(BaseModel):
    report_id: str
    kind: Literal["scan", "competitors"]
    parent_id: str  # scan_id or job_id
    scores: dict[str, int]  # e.g. {"accessibility":72,"ux":65,"flow":80}
    summary: str  # markdown
    sections: list[ReportSection]
    recommendations: list[str]
