from pydantic import BaseModel
from typing import Literal, Optional
from .scan import Status


class CompetitorRequest(BaseModel):
    store_url: str
    custom_prompt: Optional[str] = None
    product_hint: Optional[str] = None


class CompetitorCreateResponse(BaseModel):
    job_id: str
    status: Status


class CompetitorResult(BaseModel):
    id: str
    job_id: str
    name: str
    url: str
    price: Optional[float] = None
    shipping: Optional[float] = None
    tax: Optional[float] = None
    discount: Optional[str] = None
    checkout_total: Optional[float] = None
    notes: str = ""


class CompetitorJobStatus(BaseModel):
    job_id: str
    status: Status
    progress: float = 0.0
    store_url: str
    competitors: list[CompetitorResult] = []
    report_id: Optional[str] = None
    error: Optional[str] = None
