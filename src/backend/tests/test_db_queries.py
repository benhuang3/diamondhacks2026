"""Unit tests for src/db/queries.py against an in-memory-ish SQLite."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_and_get_scan(db):
    from src.db import queries

    scan_id = await queries.create_scan("https://example.com", 5)
    assert isinstance(scan_id, str)
    assert len(scan_id) > 0

    row = await queries.get_scan(scan_id)
    assert row is not None
    assert row["url"] == "https://example.com"
    assert row["status"] == "pending"
    assert row["progress"] == 0.0
    assert row["max_pages"] == 5
    assert row["report_id"] is None
    assert row["error"] is None


async def test_get_scan_missing_returns_none(db):
    from src.db import queries

    row = await queries.get_scan("does-not-exist")
    assert row is None


async def test_update_scan_applies_only_given_fields(db):
    from src.db import queries

    scan_id = await queries.create_scan("https://shop.example", 3)

    await queries.update_scan(scan_id, status="running", progress=0.5)
    row = await queries.get_scan(scan_id)
    assert row["status"] == "running"
    assert row["progress"] == 0.5
    assert row["error"] is None

    # partial update must not clobber other fields
    await queries.update_scan(scan_id, progress=0.9)
    row = await queries.get_scan(scan_id)
    assert row["status"] == "running"
    assert row["progress"] == 0.9

    # no-op when no fields given
    await queries.update_scan(scan_id)
    row2 = await queries.get_scan(scan_id)
    assert row2["status"] == "running"


async def test_findings_insert_list_count(db):
    from src.db import queries

    scan_id = await queries.create_scan("https://shop.example", 3)
    assert await queries.count_findings(scan_id) == 0

    finding = {
        "selector": "button.cta",
        "xpath": "/html/body/button",
        "bounding_box": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
        "severity": "high",
        "category": "a11y",
        "title": "Low contrast",
        "description": "Contrast ratio too low",
        "suggestion": "Darken the background",
        "page_url": "https://shop.example",
    }
    fid = await queries.insert_finding(scan_id, finding)
    assert isinstance(fid, str) and len(fid) > 0

    findings = await queries.list_findings(scan_id)
    assert len(findings) == 1
    assert findings[0]["selector"] == "button.cta"
    assert findings[0]["bounding_box"] == {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}

    assert await queries.count_findings(scan_id) == 1

    # findings for another scan isolated
    other_scan = await queries.create_scan("https://other.example", 1)
    assert await queries.count_findings(other_scan) == 0


async def test_create_and_update_competitor_job(db):
    from src.db import queries

    job_id = await queries.create_competitor_job(
        "https://store.example", "compare prices", "red running shoes"
    )
    job = await queries.get_competitor_job(job_id)
    assert job is not None
    assert job["store_url"] == "https://store.example"
    assert job["custom_prompt"] == "compare prices"
    assert job["product_hint"] == "red running shoes"
    assert job["status"] == "pending"

    await queries.update_competitor_job(job_id, status="done", progress=1.0)
    job = await queries.get_competitor_job(job_id)
    assert job["status"] == "done"
    assert job["progress"] == 1.0

    # missing job
    assert await queries.get_competitor_job("nope") is None


async def test_competitor_results_insert_list(db):
    from src.db import queries

    job_id = await queries.create_competitor_job("https://store.example", None, None)
    rid = await queries.insert_competitor_result(
        job_id,
        {
            "name": "Acme",
            "url": "https://acme.example/p/1",
            "price": 9.99,
            "shipping": 1.00,
            "tax": 0.80,
            "discount": "WELCOME",
            "checkout_total": 11.79,
            "notes": "first-time buyer deal",
        },
    )
    assert isinstance(rid, str)

    results = await queries.list_competitor_results(job_id)
    assert len(results) == 1
    assert results[0]["name"] == "Acme"
    assert results[0]["price"] == 9.99
    assert results[0]["notes"] == "first-time buyer deal"

    # empty list for unknown job
    assert await queries.list_competitor_results("nope") == []


async def test_reports_roundtrip(db):
    from src.db import queries

    report_id = await queries.create_report(
        kind="scan",
        parent_id="scan-123",
        scores={"accessibility": 72, "ux": 65},
        summary="# summary",
        sections=[{"title": "A", "body": "body"}],
        recommendations=["fix contrast", "add alt text"],
    )
    assert isinstance(report_id, str)

    row = await queries.get_report(report_id)
    assert row is not None
    assert row["kind"] == "scan"
    assert row["parent_id"] == "scan-123"
    assert row["scores"] == {"accessibility": 72, "ux": 65}
    assert row["summary"] == "# summary"
    assert row["sections"] == [{"title": "A", "body": "body"}]
    assert row["recommendations"] == ["fix contrast", "add alt text"]

    assert await queries.get_report("missing") is None
