"""Thin wrappers around the DB-backed workers so uAgent handlers can do
`url -> markdown`. Keeps the DB + scan_id plumbing out of the agent files.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from src.config.settings import settings
from src.db.client import init_db
from src.db.queries import (
    create_competitor_job,
    create_scan,
    list_competitor_results,
    list_findings,
)

from ..workers.competitor_worker import run_competitor_job
from ..workers.scan_worker import run_scan

_db_lock = asyncio.Lock()
_db_ready = False


async def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    async with _db_lock:
        if _db_ready:
            return
        await init_db()
        _db_ready = True


_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)


def extract_url(text: str) -> str | None:
    """Pull the first http(s) URL out of a user message; return None if none."""
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    url = m.group(0)
    # trim trailing sentence punctuation that commonly sticks to URLs in prose
    while url and url[-1] in ".,;:!?":
        url = url[:-1]
    # balanced parens: only strip trailing ')' if there's no matching '('
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    return url or None


def _severity_rank(sev: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(sev, 3)


def format_findings_markdown(findings: list[dict[str, Any]], url: str) -> str:
    if not findings:
        return f"No accessibility findings detected for {url}."
    findings = sorted(findings, key=lambda f: _severity_rank(f.get("severity", "low")))
    lines = [f"**Accessibility scan for {url}** — {len(findings)} finding(s)\n"]
    for i, f in enumerate(findings[:12], 1):
        sev = (f.get("severity") or "").upper()
        cat = f.get("category", "")
        title = f.get("title", "Finding")
        desc = (f.get("description") or "").strip()
        sug = (f.get("suggestion") or "").strip()
        lines.append(f"{i}. **[{sev}/{cat}]** {title}")
        if desc:
            lines.append(f"   - {desc}")
        if sug:
            lines.append(f"   - _Fix:_ {sug}")
    if len(findings) > 12:
        lines.append(f"\n_…and {len(findings) - 12} more._")
    return "\n".join(lines)


def format_competitor_markdown(results: list[dict[str, Any]], url: str) -> str:
    if not results:
        return f"No competitor results found for {url}."
    lines = [f"**Competitor analysis for {url}** — {len(results)} competitor(s)\n"]
    for i, r in enumerate(results[:8], 1):
        name = r.get("name") or "(unnamed)"
        comp_url = r.get("url") or ""
        price = r.get("price")
        shipping = r.get("shipping")
        total = r.get("checkout_total")
        notes = (r.get("notes") or "").strip()
        header = f"{i}. **{name}**"
        if comp_url:
            header += f" — {comp_url}"
        lines.append(header)
        price_bits = []
        if price is not None:
            price_bits.append(f"price ${price}")
        if shipping is not None:
            price_bits.append(f"shipping ${shipping}")
        if total is not None:
            price_bits.append(f"checkout total ${total}")
        if price_bits:
            lines.append(f"   - {', '.join(price_bits)}")
        if notes:
            lines.append(f"   - {notes[:300]}")
    return "\n".join(lines)


async def run_accessibility_scan(url: str) -> str:
    """Full scan pipeline: create DB row, run worker, read findings, format."""
    await _ensure_db()
    scan_id = await create_scan(url, settings.max_scan_pages)
    await run_scan(scan_id, url, settings.max_scan_pages)
    findings = await list_findings(scan_id)
    return format_findings_markdown(findings, url)


async def run_competitor_analysis(url: str, hint: str | None = None) -> str:
    """Full competitor pipeline: create job, run worker, read results, format."""
    await _ensure_db()
    job_id = await create_competitor_job(url, custom_prompt=None, product_hint=hint)
    await run_competitor_job(job_id, url, None, hint)
    results = await list_competitor_results(job_id)
    return format_competitor_markdown(results, url)
