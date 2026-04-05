"""Structured logging setup using structlog + stdlib integration.

By default logs go to ``logs/backend.log`` (rotated, 10MB x 3 backups)
and WARNING+ also echoes to stderr so critical events stay visible in
the terminal you launched the server from. Set ``LOG_FILE=""`` in the
environment to route all logs to stdout instead (useful in container
environments that ship stdout to a log collector).
"""

from __future__ import annotations

import logging
import logging.handlers
import pathlib
import sys

import structlog


def configure_logging(
    level: str = "INFO",
    *,
    log_file: str = "",
    log_file_max_bytes: int = 10_000_000,
    log_file_backup_count: int = 3,
) -> None:
    """Configure structlog with JSON output and stdlib logging integration.

    Call once at application startup. Safe to call multiple times —
    existing handlers on the root logger are removed first.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Build handler list. Prefer file + stderr split when a log_file is
    # configured; fall back to stdout only if the parent directory can't
    # be created (permission denied, read-only FS, etc.).
    log_file = (log_file or "").strip()
    resolved_file_path: str | None = None
    if log_file:
        try:
            path = pathlib.Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            resolved_file_path = str(path)
        except OSError as e:
            # Never silently break — warn on stderr that we're degrading.
            sys.stderr.write(
                f"[logging] log_file={log_file!r} not writable ({e}); "
                "falling back to stdout\n"
            )
            resolved_file_path = None

    formatter = logging.Formatter("%(message)s")
    handlers: list[logging.Handler] = []

    if resolved_file_path:
        file_handler = logging.handlers.RotatingFileHandler(
            resolved_file_path,
            maxBytes=log_file_max_bytes,
            backupCount=log_file_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

        # Mirror WARNING+ to stderr so critical events still reach the
        # operator without needing to tail the file.
        err_handler = logging.StreamHandler(sys.stderr)
        err_handler.setLevel(logging.WARNING)
        err_handler.setFormatter(formatter)
        handlers.append(err_handler)
    else:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(log_level)
        stdout_handler.setFormatter(formatter)
        handlers.append(stdout_handler)

    # Replace root logger handlers so configure_logging is idempotent.
    root = logging.getLogger()
    root.setLevel(log_level)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for h in handlers:
        root.addHandler(h)

    if resolved_file_path:
        logging.getLogger(__name__).info(
            "logging to file: %s (rotation: %d bytes x %d backups)",
            resolved_file_path, log_file_max_bytes, log_file_backup_count,
        )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name) if name else structlog.get_logger()
