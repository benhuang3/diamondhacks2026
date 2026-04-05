"""Async query functions (return dicts, not ORM objects).

Signatures locked by CONTRACTS.md §3. Each function manages its own session.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete as sa_delete, func, select, update

from src.db.client import AsyncSessionLocal
from src.db.schema import (
    CompetitorJob,
    CompetitorResult,
    Report,
    Scan,
    ScanFinding,
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _scan_to_dict(s: Scan) -> dict[str, Any]:
    return {
        "id": s.id,
        "url": s.url,
        "status": s.status,
        "progress": s.progress,
        "max_pages": s.max_pages,
        "report_id": s.report_id,
        "error": s.error,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def _finding_to_dict(f: ScanFinding) -> dict[str, Any]:
    return {
        "id": f.id,
        "scan_id": f.scan_id,
        "selector": f.selector,
        "xpath": f.xpath,
        "bounding_box": f.bounding_box,
        "severity": f.severity,
        "category": f.category,
        "title": f.title,
        "description": f.description,
        "suggestion": f.suggestion,
        "page_url": f.page_url,
        "created_at": f.created_at,
    }


def _job_to_dict(j: CompetitorJob) -> dict[str, Any]:
    return {
        "id": j.id,
        "store_url": j.store_url,
        "custom_prompt": j.custom_prompt,
        "product_hint": j.product_hint,
        "status": j.status,
        "progress": j.progress,
        "report_id": j.report_id,
        "error": j.error,
        "created_at": j.created_at,
        "updated_at": j.updated_at,
    }


def _result_to_dict(r: CompetitorResult) -> dict[str, Any]:
    return {
        "id": r.id,
        "job_id": r.job_id,
        "name": r.name,
        "url": r.url,
        "price": r.price,
        "shipping": r.shipping,
        "tax": r.tax,
        "discount": r.discount,
        "checkout_total": r.checkout_total,
        "raw_data": r.raw_data,
        "notes": r.notes,
        "created_at": r.created_at,
    }


def _report_to_dict(r: Report) -> dict[str, Any]:
    return {
        "id": r.id,
        "kind": r.kind,
        "parent_id": r.parent_id,
        "scores": r.scores,
        "summary": r.summary,
        "sections": r.sections,
        "recommendations": r.recommendations,
        "created_at": r.created_at,
    }


# ---------------------------------------------------------------------------
# scans
# ---------------------------------------------------------------------------

async def create_scan(url: str, max_pages: int) -> str:
    scan_id = _new_id()
    async with AsyncSessionLocal() as session:
        session.add(
            Scan(
                id=scan_id,
                url=url,
                status="pending",
                progress=0.0,
                max_pages=max_pages,
            )
        )
        await session.commit()
    return scan_id


async def get_scan(scan_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(Scan, scan_id)
        if row is None:
            return None
        return _scan_to_dict(row)


async def update_scan(
    scan_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    report_id: str | None = None,
) -> None:
    values: dict[str, Any] = {}
    if status is not None:
        values["status"] = status
    if progress is not None:
        values["progress"] = progress
    if error is not None:
        values["error"] = error
    if report_id is not None:
        values["report_id"] = report_id

    if not values:
        return

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Scan).where(Scan.id == scan_id).values(**values)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------

async def insert_finding(scan_id: str, finding: dict) -> str:
    finding_id = finding.get("id") or _new_id()
    async with AsyncSessionLocal() as session:
        session.add(
            ScanFinding(
                id=finding_id,
                scan_id=scan_id,
                selector=finding["selector"],
                xpath=finding.get("xpath"),
                bounding_box=finding.get("bounding_box"),
                severity=finding["severity"],
                category=finding["category"],
                title=finding["title"],
                description=finding["description"],
                suggestion=finding["suggestion"],
                page_url=finding["page_url"],
            )
        )
        await session.commit()
    return finding_id


async def insert_findings_bulk(scan_id: str, findings: list[dict]) -> list[str]:
    """Insert many findings in a single transaction (one commit, one fsync).

    Returns the generated IDs in input order. Use this from workers that
    emit batches; :func:`insert_finding` remains for incremental writes.
    """
    if not findings:
        return []
    rows: list[ScanFinding] = []
    ids: list[str] = []
    for f in findings:
        fid = f.get("id") or _new_id()
        ids.append(fid)
        rows.append(
            ScanFinding(
                id=fid,
                scan_id=scan_id,
                selector=f["selector"],
                xpath=f.get("xpath"),
                bounding_box=f.get("bounding_box"),
                severity=f["severity"],
                category=f["category"],
                title=f["title"],
                description=f["description"],
                suggestion=f["suggestion"],
                page_url=f["page_url"],
            )
        )
    async with AsyncSessionLocal() as session:
        session.add_all(rows)
        await session.commit()
    return ids


async def list_findings(scan_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ScanFinding)
            .where(ScanFinding.scan_id == scan_id)
            .order_by(ScanFinding.created_at.asc())
        )
        rows = result.scalars().all()
        return [_finding_to_dict(r) for r in rows]


async def count_findings(scan_id: str) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ScanFinding)
            .where(ScanFinding.scan_id == scan_id)
        )
        return int(result.scalar_one())


# ---------------------------------------------------------------------------
# competitor jobs
# ---------------------------------------------------------------------------

async def create_competitor_job(
    store_url: str,
    custom_prompt: str | None,
    product_hint: str | None,
) -> str:
    job_id = _new_id()
    async with AsyncSessionLocal() as session:
        session.add(
            CompetitorJob(
                id=job_id,
                store_url=store_url,
                custom_prompt=custom_prompt,
                product_hint=product_hint,
                status="pending",
                progress=0.0,
            )
        )
        await session.commit()
    return job_id


async def get_competitor_job(job_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(CompetitorJob, job_id)
        if row is None:
            return None
        return _job_to_dict(row)


async def update_competitor_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    report_id: str | None = None,
) -> None:
    values: dict[str, Any] = {}
    if status is not None:
        values["status"] = status
    if progress is not None:
        values["progress"] = progress
    if error is not None:
        values["error"] = error
    if report_id is not None:
        values["report_id"] = report_id

    if not values:
        return

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(CompetitorJob)
            .where(CompetitorJob.id == job_id)
            .values(**values)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# competitor results
# ---------------------------------------------------------------------------

async def insert_competitor_result(job_id: str, result: dict) -> str:
    result_id = result.get("id") or _new_id()
    async with AsyncSessionLocal() as session:
        session.add(
            CompetitorResult(
                id=result_id,
                job_id=job_id,
                name=result["name"],
                url=result["url"],
                price=result.get("price"),
                shipping=result.get("shipping"),
                tax=result.get("tax"),
                discount=result.get("discount"),
                checkout_total=result.get("checkout_total"),
                raw_data=result.get("raw_data"),
                notes=result.get("notes", ""),
            )
        )
        await session.commit()
    return result_id


async def list_competitor_results(job_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CompetitorResult)
            .where(CompetitorResult.job_id == job_id)
            .order_by(CompetitorResult.created_at.asc())
        )
        rows = result.scalars().all()
        return [_result_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

async def create_report(
    kind: str,
    parent_id: str,
    scores: dict,
    summary: str,
    sections: list[dict],
    recommendations: list[str],
) -> str:
    report_id = _new_id()
    async with AsyncSessionLocal() as session:
        session.add(
            Report(
                id=report_id,
                kind=kind,
                parent_id=parent_id,
                scores=scores,
                summary=summary,
                sections=sections,
                recommendations=recommendations,
            )
        )
        await session.commit()
    return report_id


async def get_report(report_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(Report, report_id)
        if row is None:
            return None
        return _report_to_dict(row)
