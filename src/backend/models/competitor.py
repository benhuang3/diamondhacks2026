from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from .scan import Status
from ..security.url_guard import UnsafeURLError, validate_public_url


class CompetitorRequest(BaseModel):
    store_url: str = Field(..., max_length=2048)
    custom_prompt: Optional[str] = Field(None, max_length=2000)
    product_hint: Optional[str] = Field(None, max_length=500)

    @field_validator("store_url")
    @classmethod
    def _validate_store_url(cls, v: str) -> str:
        try:
            return validate_public_url(v)
        except UnsafeURLError as e:
            raise ValueError(str(e)) from e


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
