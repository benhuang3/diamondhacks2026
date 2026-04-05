# Shared Contracts — Phase 2 (locked, do not change without coordinating)

All three parallel agents MUST conform to these contracts. Any deviation breaks integration in Phase 3.

## 1. Status enum (shared)

```python
Status = Literal["pending", "running", "done", "failed"]
```

## 2. Pydantic models (Agent A owns `src/backend/models/`, Agent C imports shapes)

### `src/backend/models/scan.py`

```python
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
```

### `src/backend/models/competitor.py`

```python
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
```

### `src/backend/models/report.py`

```python
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
```

## 3. DB query function signatures (Agent C implements in `src/db/queries.py`, Agent A calls)

All async. Return plain dicts (not pydantic models) — caller wraps.

```python
# scans
async def create_scan(url: str, max_pages: int) -> str: ...  # returns scan_id (uuid)
async def get_scan(scan_id: str) -> dict | None: ...
async def update_scan(
    scan_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    report_id: str | None = None,
) -> None: ...

# findings
async def insert_finding(scan_id: str, finding: dict) -> str: ...  # returns finding id
async def list_findings(scan_id: str) -> list[dict]: ...
async def count_findings(scan_id: str) -> int: ...

# competitor jobs
async def create_competitor_job(store_url: str, custom_prompt: str | None, product_hint: str | None) -> str: ...
async def get_competitor_job(job_id: str) -> dict | None: ...
async def update_competitor_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    report_id: str | None = None,
) -> None: ...

# competitor results
async def insert_competitor_result(job_id: str, result: dict) -> str: ...
async def list_competitor_results(job_id: str) -> list[dict]: ...

# reports
async def create_report(
    kind: str,
    parent_id: str,
    scores: dict,
    summary: str,
    sections: list[dict],
    recommendations: list[str],
) -> str: ...  # returns report_id
async def get_report(report_id: str) -> dict | None: ...
```

### DB initialization helper (Agent C implements)

```python
async def init_db() -> None: ...  # creates tables if not exist; called at FastAPI startup
```

## 4. Settings (Agent C owns `src/config/settings.py`, Agent A imports)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-6"

    # DB
    database_url: str = "sqlite+aiosqlite:///./storefront.db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,chrome-extension://*"

    # Browser Use
    browser_use_api_key: str = ""
    browser_use_headless: bool = True
    browser_use_timeout_ms: int = 30000
    max_scan_pages: int = 5
    max_competitors: int = 5

    log_level: str = "INFO"

settings = Settings()
```

## 5. HTTP API (Agent A implements, Agent B consumes)

Base URL: `http://localhost:8000`

| Method | Path | Request body | Response |
|---|---|---|---|
| GET  | `/health` | — | `{"status":"ok"}` |
| POST | `/scan` | `ScanRequest` | `202 ScanCreateResponse` |
| GET  | `/scan/{scan_id}` | — | `200 ScanStatus` or `404` |
| GET  | `/annotations/{scan_id}` | — | `200 AnnotationsResponse` or `404` |
| POST | `/competitors` | `CompetitorRequest` | `202 CompetitorCreateResponse` |
| GET  | `/competitors/{job_id}` | — | `200 CompetitorJobStatus` or `404` |
| GET  | `/report/{report_id}` | — | `200 Report` or `404` |

CORS: allow `http://localhost:3000` and `chrome-extension://*`.

## 6. Chrome extension ↔ backend

- Extension calls `POST /scan` and polls `GET /scan/{id}` every 3s.
- When `status=done`, calls `GET /annotations/{scan_id}` and content script injects highlights.
- Content script resolves each finding by: `selector` first → `xpath` fallback → `bounding_box` absolute overlay fallback.
- Severity CSS classes: `sr-highlight sr-sev-high | sr-sev-medium | sr-sev-low`.

## 7. File ownership (strict — do not cross boundaries)

| Agent | Owns | May import from |
|---|---|---|
| A (backend) | `src/backend/**` | `src/config/**`, `src/db/**` |
| B (frontend) | `src/frontend/web/**`, `src/frontend/extension/**` | nothing (fetch API only) |
| C (config+db) | `src/config/**`, `src/db/**`, `src/db/migrations/*.sql` | nothing (self-contained) |

## 8. Stub guidance (so agents can build in parallel without live deps)

- Agent A's workers MUST have a `DEMO_MODE` path that produces fake findings/competitors without calling BrowserUse or Anthropic, triggered when `ANTHROPIC_API_KEY` is empty or placeholder. This lets Phase 3 integration test end-to-end without real keys.
- Agent B MUST NOT assume the backend is running — use a `NEXT_PUBLIC_DEMO_MODE=true` env flag to display seeded data when fetch fails.
- Agent C MUST include `db/seed.py` that inserts one demo scan with 3 findings + one demo competitor job, so Phase 3 has data to display immediately.
