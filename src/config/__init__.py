"""Configuration package: settings, logging, constants."""

from .settings import settings
from .constants import (
    SEVERITY_LEVELS,
    CATEGORIES,
    STATUSES,
    REPORT_KINDS,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_COMPETITORS,
)
from .logging import configure_logging

__all__ = [
    "settings",
    "configure_logging",
    "SEVERITY_LEVELS",
    "CATEGORIES",
    "STATUSES",
    "REPORT_KINDS",
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_COMPETITORS",
]
