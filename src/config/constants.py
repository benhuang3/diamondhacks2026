"""Shared constants: enums, timeouts, defaults.

Keep these values aligned with CONTRACTS.md (severity/category/status Literals).
"""

from __future__ import annotations

# ---- Enums (mirror pydantic Literals in backend models) -------------------

SEVERITY_LEVELS: list[str] = ["high", "medium", "low"]
"""Valid severity values for scan findings."""

CATEGORIES: list[str] = ["a11y", "ux", "contrast", "nav"]
"""Valid category values for scan findings."""

STATUSES: list[str] = ["pending", "running", "done", "failed"]
"""Valid status values for scans and competitor_jobs."""

REPORT_KINDS: list[str] = ["scan", "competitors"]
"""Valid report kinds."""

# ---- Defaults / timeouts --------------------------------------------------

DEFAULT_TIMEOUT_MS: int = 30000
"""Default browser / HTTP timeout in milliseconds."""

DEFAULT_POLL_INTERVAL_S: float = 3.0
"""Default polling interval for frontend/extension status polls."""

DEFAULT_MAX_PAGES: int = 5
"""Default max pages to crawl per scan."""

DEFAULT_MAX_COMPETITORS: int = 5
"""Default max competitors to analyze per job."""

# ---- Scoring key sets (per CONTRACTS.md §7-5) -----------------------------

SCAN_SCORE_KEYS: list[str] = ["accessibility", "ux", "flow"]
COMPETITOR_SCORE_KEYS: list[str] = ["pricing", "value", "experience"]
