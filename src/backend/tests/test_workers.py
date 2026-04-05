"""Unit tests for workers (demo paths + JSON extraction helpers)."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# _extract_json_array (scan + competitor share the same helper)
# ---------------------------------------------------------------------------


def test_extract_json_array_plain():
    from src.backend.workers.scan_worker import _extract_json_array

    assert _extract_json_array('[{"a":1},{"a":2}]') == [{"a": 1}, {"a": 2}]


def test_extract_json_array_with_prose():
    from src.backend.workers.scan_worker import _extract_json_array

    text = 'Sure, here you go: [{"selector":"body"}] thanks!'
    assert _extract_json_array(text) == [{"selector": "body"}]


def test_extract_json_array_fenced_json():
    from src.backend.workers.scan_worker import _extract_json_array

    text = """```json
[{"x": 1}]
```"""
    assert _extract_json_array(text) == [{"x": 1}]


def test_extract_json_array_empty_on_garbage():
    from src.backend.workers.scan_worker import _extract_json_array

    assert _extract_json_array("totally not json") == []


def test_extract_json_array_competitor_worker_variant():
    from src.backend.workers.competitor_worker import _extract_json_array

    text = '```json\n[{"name":"A","url":"https://a.x"}]\n```'
    assert _extract_json_array(text) == [{"name": "A", "url": "https://a.x"}]


# ---------------------------------------------------------------------------
# scan_worker demo path end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scan_demo_path_completes(db, monkeypatch):
    """Force demo mode and drive a scan to completion; verify state + findings."""
    from src.backend.workers import scan_worker
    from src.backend.agents import claude_client
    from src.db import queries

    # Force demo mode regardless of settings.
    monkeypatch.setattr(claude_client, "is_demo_mode", lambda: True)
    # Use scan_worker's own reference too.
    monkeypatch.setattr(scan_worker, "is_demo_mode", lambda: True)
    # Make sleeps instantaneous.
    import asyncio as _asyncio

    async def _nosleep(_s):
        return None

    monkeypatch.setattr(scan_worker.asyncio, "sleep", _nosleep)

    # Also stub the report generator to avoid calling Claude.
    async def _fake_report(scan_id, url):
        rid = await queries.create_report(
            kind="scan",
            parent_id=scan_id,
            scores={"accessibility": 70, "ux": 65, "flow": 80},
            summary="demo",
            sections=[],
            recommendations=[],
        )
        await queries.update_scan(scan_id, report_id=rid)
        return rid

    monkeypatch.setattr(scan_worker, "generate_scan_report", _fake_report)

    scan_id = await queries.create_scan("https://shop.example", 2)
    await scan_worker.run_scan(scan_id, "https://shop.example", 2)

    row = await queries.get_scan(scan_id)
    assert row["status"] == "done"
    assert row["progress"] == 1.0
    assert row["report_id"] is not None

    findings = await queries.list_findings(scan_id)
    assert len(findings) >= 6  # DEMO_FINDINGS_TEMPLATE yields 6-8
    # all rows must carry the requested page_url
    for f in findings:
        assert f["page_url"] == "https://shop.example"
        assert f["severity"] in {"high", "medium", "low"}
        assert f["category"] in {"a11y", "ux", "contrast", "nav"}


@pytest.mark.asyncio
async def test_run_scan_marks_failed_on_unhandled_error(db, monkeypatch):
    from src.backend.workers import scan_worker
    from src.db import queries

    monkeypatch.setattr(scan_worker, "is_demo_mode", lambda: True)

    async def _explode(*a, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scan_worker, "_run_demo", _explode)

    scan_id = await queries.create_scan("https://x.example", 1)
    await scan_worker.run_scan(scan_id, "https://x.example", 1)

    row = await queries.get_scan(scan_id)
    assert row["status"] == "failed"
    assert row["error"] and "kaboom" in row["error"]


# ---------------------------------------------------------------------------
# competitor_worker demo path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_competitor_demo_path_completes(db, monkeypatch):
    from src.backend.workers import competitor_worker
    from src.db import queries

    monkeypatch.setattr(competitor_worker, "is_demo_mode", lambda: True)

    async def _nosleep(_s):
        return None

    monkeypatch.setattr(competitor_worker.asyncio, "sleep", _nosleep)

    async def _fake_report(job_id, store_url):
        rid = await queries.create_report(
            kind="competitors",
            parent_id=job_id,
            scores={"price": 80},
            summary="demo",
            sections=[],
            recommendations=[],
        )
        await queries.update_competitor_job(job_id, report_id=rid)
        return rid

    monkeypatch.setattr(competitor_worker, "generate_competitor_report", _fake_report)

    job_id = await queries.create_competitor_job("https://s.example", None, None)
    await competitor_worker.run_competitor_job(job_id, "https://s.example", None, None)

    job = await queries.get_competitor_job(job_id)
    assert job["status"] == "done"
    assert job["progress"] == 1.0
    assert job["report_id"] is not None

    results = await queries.list_competitor_results(job_id)
    assert len(results) >= 1
    for r in results:
        assert r["name"]
        assert r["url"].startswith("http")


@pytest.mark.asyncio
async def test_run_competitor_marks_failed_on_error(db, monkeypatch):
    from src.backend.workers import competitor_worker
    from src.db import queries

    monkeypatch.setattr(competitor_worker, "is_demo_mode", lambda: True)

    async def _explode(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(competitor_worker, "_run_demo", _explode)

    job_id = await queries.create_competitor_job("https://s.example", None, None)
    await competitor_worker.run_competitor_job(job_id, "https://s.example", None, None)

    row = await queries.get_competitor_job(job_id)
    assert row["status"] == "failed"
    assert row["error"] and "boom" in row["error"]
