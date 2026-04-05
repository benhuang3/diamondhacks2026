"""Per-request context middleware.

Assigns a request ID (honoring an inbound ``X-Request-ID`` header), binds it
into structlog's contextvars so every log line emitted during the request
carries it, emits one structured access-log line per request, and records a
counter for Prometheus.
"""

from __future__ import annotations

import re
import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from ..observability.metrics import metrics

_log = structlog.get_logger("http")

# Keep inbound request IDs to a safe subset so an attacker can't inject
# newlines, quotes, or JSON delimiters into our structured logs.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        inbound = request.headers.get("x-request-id", "").strip()
        if inbound and _REQUEST_ID_RE.match(inbound):
            request_id = inbound
        else:
            request_id = uuid.uuid4().hex[:16]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            _log.exception(
                "request.error",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise
        else:
            duration_ms = (time.perf_counter() - start) * 1000
            route_path = _route_template(request) or request.url.path
            _log.info(
                "request",
                method=request.method,
                path=request.url.path,
                route=route_path,
                status=status_code,
                duration_ms=round(duration_ms, 2),
            )
            metrics.inc(
                "http_requests_total",
                method=request.method,
                route=route_path,
                status=str(status_code),
            )
            response.headers["X-Request-ID"] = request_id
            return response


def _route_template(request: Request) -> str | None:
    """Return the matched route's path template (e.g. ``/scan/{scan_id}``).

    Using the template instead of the raw URL keeps metric cardinality bounded.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else None
