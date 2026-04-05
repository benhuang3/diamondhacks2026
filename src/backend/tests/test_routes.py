"""Integration tests for FastAPI routes via httpx ASGI transport."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_post_scan_returns_202_and_persists(client, db):
    from src.db import queries

    r = await client.post("/scan", json={"url": "https://example.com", "max_pages": 3})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    scan_id = body["scan_id"]
    assert isinstance(scan_id, str) and scan_id

    row = await queries.get_scan(scan_id)
    # Note: FastAPI BackgroundTasks run AFTER the response is returned; in
    # httpx ASGITransport they've already run by the time `r` resolves. So
    # the scan may be done, running, or failed by now. We only assert that
    # the row exists and has a valid status.
    assert row is not None
    assert row["status"] in {"pending", "running", "done", "failed"}


async def test_get_scan_404_for_unknown(client):
    r = await client.get("/scan/does-not-exist")
    assert r.status_code == 404


async def test_get_scan_returns_status(client, db):
    from src.db import queries

    scan_id = await queries.create_scan("https://foo.example", 1)
    await queries.update_scan(scan_id, status="running", progress=0.25)

    r = await client.get(f"/scan/{scan_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["scan_id"] == scan_id
    assert body["status"] == "running"
    assert body["progress"] == 0.25
    assert body["url"] == "https://foo.example"
    assert body["findings_count"] == 0


async def test_annotations_404_for_unknown(client):
    r = await client.get("/annotations/nope")
    assert r.status_code == 404


async def test_annotations_returns_findings(client, db):
    from src.db import queries

    scan_id = await queries.create_scan("https://foo.example", 1)
    await queries.insert_finding(
        scan_id,
        {
            "selector": "button.cta",
            "severity": "high",
            "category": "ux",
            "title": "t",
            "description": "d",
            "suggestion": "s",
            "page_url": "https://foo.example",
        },
    )

    r = await client.get(f"/annotations/{scan_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["scan_id"] == scan_id
    assert body["url"] == "https://foo.example"
    assert len(body["annotations"]) == 1
    assert body["annotations"][0]["selector"] == "button.cta"
    assert body["annotations"][0]["severity"] == "high"


async def test_post_competitors_returns_202(client, db):
    from src.db import queries

    r = await client.post(
        "/competitors",
        json={
            "store_url": "https://store.example",
            "custom_prompt": "compare",
            "product_hint": "sneakers",
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    job_id = body["job_id"]
    assert isinstance(job_id, str) and job_id

    row = await queries.get_competitor_job(job_id)
    assert row is not None


async def test_get_competitor_404(client):
    r = await client.get("/competitors/nope")
    assert r.status_code == 404


async def test_get_competitor_returns_status(client, db):
    from src.db import queries

    job_id = await queries.create_competitor_job("https://s.example", None, None)
    await queries.update_competitor_job(job_id, status="done", progress=1.0)
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
            "notes": "",
        },
    )

    r = await client.get(f"/competitors/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["status"] == "done"
    assert body["progress"] == 1.0
    assert len(body["competitors"]) == 1
    assert body["competitors"][0]["name"] == "Acme"


async def test_competitors_validation_error(client):
    r = await client.post("/competitors", json={})  # missing store_url
    assert r.status_code == 422


async def test_scan_validation_error(client):
    r = await client.post("/scan", json={})  # missing url
    assert r.status_code == 422


async def test_get_report_404(client):
    r = await client.get("/report/nope")
    assert r.status_code == 404


async def test_get_report_roundtrip(client, db):
    from src.db import queries

    report_id = await queries.create_report(
        kind="scan",
        parent_id="scan-abc",
        scores={"accessibility": 80, "ux": 70},
        summary="# summary",
        sections=[
            {"title": "Findings", "body": "body-md", "chart": None},
            {"title": "Details", "body": "more", "chart": {"type": "bar", "data": []}},
        ],
        recommendations=["do thing"],
    )

    r = await client.get(f"/report/{report_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["report_id"] == report_id
    assert body["kind"] == "scan"
    assert body["parent_id"] == "scan-abc"
    assert body["scores"]["accessibility"] == 80
    assert len(body["sections"]) == 2
    assert body["sections"][0]["title"] == "Findings"
    assert body["recommendations"] == ["do thing"]
