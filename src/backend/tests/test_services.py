"""Unit tests for scan_service and competitor_service.

The services are thin wrappers around db/queries — so we exercise them
against the live in-memory DB fixture rather than mocking every call; that
still counts as unit-scope since no external services (Claude/BrowserUse)
are touched.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# scan_service
# ---------------------------------------------------------------------------


async def test_start_scan_creates_row(db):
    from src.backend.services import scan_service
    from src.db import queries

    scan_id = await scan_service.start_scan("https://foo.example", 7)
    row = await queries.get_scan(scan_id)
    assert row is not None
    assert row["url"] == "https://foo.example"
    assert row["max_pages"] == 7


async def test_fetch_scan_status_missing_returns_none(db):
    from src.backend.services import scan_service

    assert await scan_service.fetch_scan_status("nope") is None


async def test_fetch_scan_status_reflects_db(db):
    from src.backend.services import scan_service
    from src.db import queries

    scan_id = await queries.create_scan("https://foo.example", 2)
    await queries.update_scan(scan_id, status="running", progress=0.5)
    await queries.insert_finding(
        scan_id,
        {
            "selector": "body",
            "severity": "low",
            "category": "ux",
            "title": "t",
            "description": "d",
            "suggestion": "s",
            "page_url": "https://foo.example",
        },
    )

    status = await scan_service.fetch_scan_status(scan_id)
    assert status is not None
    assert status.scan_id == scan_id
    assert status.status == "running"
    assert status.progress == 0.5
    assert status.url == "https://foo.example"
    assert status.findings_count == 1
    assert status.report_id is None


async def test_fetch_annotations_returns_none_for_missing(db):
    from src.backend.services import scan_service

    assert await scan_service.fetch_annotations("nope") is None


async def test_fetch_annotations_maps_fields(db):
    from src.backend.services import scan_service
    from src.db import queries

    scan_id = await queries.create_scan("https://foo.example", 1)
    await queries.insert_finding(
        scan_id,
        {
            "selector": "a.link",
            "xpath": "/html/body/a",
            "bounding_box": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
            "severity": "medium",
            "category": "nav",
            "title": "Focus ring missing",
            "description": "…",
            "suggestion": "add focus-visible",
            "page_url": "https://foo.example",
        },
    )

    resp = await scan_service.fetch_annotations(scan_id)
    assert resp is not None
    assert resp.scan_id == scan_id
    assert resp.url == "https://foo.example"
    assert len(resp.annotations) == 1
    f = resp.annotations[0]
    assert f.selector == "a.link"
    assert f.xpath == "/html/body/a"
    assert f.bounding_box is not None
    assert f.bounding_box.x == 1.0 and f.bounding_box.w == 3.0
    assert f.severity == "medium"
    assert f.category == "nav"


async def test_fetch_annotations_tolerates_bad_bbox(db):
    """_finding_from_row should swallow a malformed bbox."""
    from src.backend.services import scan_service

    # Fabricate a row directly without going through insert_finding (which is
    # strict). _finding_from_row is a pure mapper.
    row = {
        "id": "x",
        "scan_id": "s",
        "selector": "body",
        "xpath": None,
        "bounding_box": {"x": "not-a-number"},
        "severity": "low",
        "category": "ux",
        "title": "t",
        "description": "d",
        "suggestion": "s",
        "page_url": "https://foo.example",
    }
    f = scan_service._finding_from_row(row, "s")
    assert f.bounding_box is None


# ---------------------------------------------------------------------------
# competitor_service
# ---------------------------------------------------------------------------


async def test_start_competitor_job_creates_row(db):
    from src.backend.services import competitor_service
    from src.db import queries

    job_id = await competitor_service.start_competitor_job(
        "https://store.example", "prompt", "hint"
    )
    job = await queries.get_competitor_job(job_id)
    assert job is not None
    assert job["store_url"] == "https://store.example"
    assert job["custom_prompt"] == "prompt"
    assert job["product_hint"] == "hint"


async def test_fetch_competitor_job_missing(db):
    from src.backend.services import competitor_service

    assert await competitor_service.fetch_competitor_job("nope") is None


async def test_fetch_competitor_job_maps_results(db):
    from src.backend.services import competitor_service
    from src.db import queries

    job_id = await queries.create_competitor_job("https://s.example", None, None)
    await queries.update_competitor_job(job_id, status="running", progress=0.5)
    await queries.insert_competitor_result(
        job_id,
        {
            "name": "Acme",
            "url": "https://acme.example",
            "price": 10.0,
            "shipping": 2.0,
            "tax": 1.0,
            "discount": None,
            "checkout_total": 13.0,
            "notes": "n/a",
        },
    )

    status = await competitor_service.fetch_competitor_job(job_id)
    assert status is not None
    assert status.job_id == job_id
    assert status.store_url == "https://s.example"
    assert status.status == "running"
    assert status.progress == 0.5
    assert len(status.competitors) == 1
    c = status.competitors[0]
    assert c.name == "Acme"
    assert c.checkout_total == 13.0
    assert c.notes == "n/a"
