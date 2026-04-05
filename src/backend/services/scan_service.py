"""Scan business logic: create, fetch status, list annotations."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Deque, Optional

from src.config.settings import settings
from src.db.queries import (
    count_findings,
    create_scan,
    get_finding,
    get_scan,
    list_findings,
    list_scans,
)

from ..agents import accessibility_prompts as prompts
from ..agents.claude_client import ClaudeClient, DemoFallbackError, is_demo_mode
from ..agents.fix_validator import validate_fix_operation
from ..agents.json_utils import extract_json_object
from ..models.scan import (
    AnnotationsResponse,
    BoundingBox,
    FixOperation,
    ScanFinding,
    ScanStatus,
    ScanStep,
    ScanSummary,
)
from ..observability import scan_log

log = logging.getLogger(__name__)


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


# --- Fix generation -------------------------------------------------------

class FixRateLimitError(RuntimeError):
    """Raised when a scan has exceeded its per-minute fix budget."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("fix rate limit exceeded")
        self.retry_after = retry_after


class FindingNotFoundError(RuntimeError):
    pass


_FIX_RATE_LOCK = threading.Lock()
# LRU-bounded — one bucket per scan_id. Older scan buckets get evicted
# once we hit the cap so a long-lived server doesn't leak memory.
_FIX_RATE_BUCKETS: "OrderedDict[str, Deque[float]]" = OrderedDict()
_FIX_RATE_MAX_BUCKETS = 2000
# Dedupe cache — repeated POSTs for the same finding within the TTL
# return the cached operation instead of burning another Claude call.
_FIX_DEDUPE_TTL_S = 30.0
_FIX_DEDUPE_CACHE: dict[str, tuple[float, FixOperation]] = {}


def _check_fix_rate_limit(scan_id: str) -> None:
    window = 60.0
    limit = settings.rate_limit_fix_per_min
    now = time.monotonic()
    with _FIX_RATE_LOCK:
        bucket = _FIX_RATE_BUCKETS.get(scan_id)
        if bucket is None:
            bucket = deque()
            _FIX_RATE_BUCKETS[scan_id] = bucket
            while len(_FIX_RATE_BUCKETS) > _FIX_RATE_MAX_BUCKETS:
                _FIX_RATE_BUCKETS.popitem(last=False)
        else:
            _FIX_RATE_BUCKETS.move_to_end(scan_id)
        cutoff = now - window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window - (now - bucket[0])))
            raise FixRateLimitError(retry_after)
        bucket.append(now)


def _dedupe_lookup(finding_id: str) -> Optional[FixOperation]:
    entry = _FIX_DEDUPE_CACHE.get(finding_id)
    if not entry:
        return None
    ts, op = entry
    if time.monotonic() - ts > _FIX_DEDUPE_TTL_S:
        _FIX_DEDUPE_CACHE.pop(finding_id, None)
        return None
    return op


def _dedupe_store(finding_id: str, op: FixOperation) -> None:
    # Don't cache validator rejections — user retries within the 30s
    # window should get a fresh Claude call rather than the stale "none".
    if op.kind == "none":
        _FIX_DEDUPE_CACHE.pop(finding_id, None)
        return
    _FIX_DEDUPE_CACHE[finding_id] = (time.monotonic(), op)
    # Opportunistic trim.
    if len(_FIX_DEDUPE_CACHE) > 1000:
        cutoff = time.monotonic() - _FIX_DEDUPE_TTL_S
        for k in [k for k, (ts, _) in _FIX_DEDUPE_CACHE.items() if ts < cutoff]:
            _FIX_DEDUPE_CACHE.pop(k, None)


def _demo_fix_for(finding: dict[str, Any]) -> FixOperation:
    """Deterministic fix for demo-mode / fallback when Claude is unavailable.
    Keyed on finding.category so each severity/category gets something
    visually distinct in the UI."""
    selector = str(finding.get("selector") or "body")[:500]
    category = str(finding.get("category") or "ux").lower()
    if category == "contrast":
        return FixOperation(
            kind="css",
            rules=(
                f"{selector} {{ color: #111111 !important; "
                f"background-color: #ffffff !important; }}"
            ),
        )
    if category == "a11y":
        title = str(finding.get("title") or "")[:80]
        alt = f"{title} (added by dropper.ai)" if title else "image"
        return FixOperation(
            kind="attribute",
            selector=selector,
            name="alt",
            value=alt[:200],
        )
    if category == "nav":
        return FixOperation(
            kind="css",
            rules=(
                f"{selector}:focus-visible {{ outline: 2px solid #3366FF; "
                f"outline-offset: 2px; }}"
            ),
        )
    # ux bucket: no safe DOM-only fix in demo mode.
    return FixOperation(
        kind="none",
        reason="demo mode — ux issues need a real Claude call",
    )


async def generate_finding_fix(
    scan_id: str, finding_id: str
) -> FixOperation:
    """Generate + validate a FixOperation for a single finding.

    Raises :class:`FindingNotFoundError` if the finding doesn't exist
    or doesn't belong to ``scan_id``. Raises :class:`FixRateLimitError`
    when the per-scan fix budget is exhausted.
    """
    finding = await get_finding(finding_id)
    if not finding or finding.get("scan_id") != scan_id:
        raise FindingNotFoundError()

    cached = _dedupe_lookup(finding_id)
    if cached is not None:
        return cached

    _check_fix_rate_limit(scan_id)

    if is_demo_mode():
        op = _demo_fix_for(finding)
        _dedupe_store(finding_id, op)
        return op

    prompt_text = prompts.FIX_FINDING_PROMPT.format(
        title=_truncate(finding.get("title"), 200),
        severity=finding.get("severity", "medium"),
        category=finding.get("category", "ux"),
        selector=_truncate(finding.get("selector"), 300),
        description=_truncate(finding.get("description"), 400),
        suggestion=_truncate(finding.get("suggestion"), 400),
    )
    client = ClaudeClient()
    try:
        text = await client.complete(
            prompt_text,
            system=prompts.SYSTEM_FIX_FINDING,
            max_tokens=512,
        )
    except DemoFallbackError as e:
        log.info("fix for %s falling back to demo: %s", finding_id, e)
        op = _demo_fix_for(finding)
        _dedupe_store(finding_id, op)
        return op

    parsed = extract_json_object(text)
    op = validate_fix_operation(parsed)
    _dedupe_store(finding_id, op)
    return op


def _truncate(value: Any, n: int) -> str:
    s = str(value or "").strip()
    return s[:n]
