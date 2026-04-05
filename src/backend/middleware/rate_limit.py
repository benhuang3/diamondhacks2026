"""In-process sliding-window rate limiter.

Keyed on ``(method, path, client_ip)``. Intended for expensive endpoints
that spawn background jobs (Claude + BrowserUse). A real deployment should
front this with an edge limiter; this middleware is a cost-bomb backstop.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..observability.metrics import metrics


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        rules: dict[tuple[str, str], tuple[int, int]],
    ) -> None:
        """
        Args:
            rules: ``{(METHOD, path): (max_requests, window_seconds)}``.
                Only exact matches are rate-limited; everything else passes
                through.
        """
        super().__init__(app)
        self._rules = rules
        self._hits: dict[tuple[str, str, str], Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        route_key = (request.method.upper(), request.url.path)
        rule = self._rules.get(route_key)
        if rule is not None:
            max_req, window = rule
            client_ip = request.client.host if request.client else "unknown"
            bucket_key = (route_key[0], route_key[1], client_ip)
            now = time.monotonic()
            bucket = self._hits[bucket_key]
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_req:
                retry_after = max(1, int(window - (now - bucket[0])))
                metrics.inc(
                    "http_rate_limited_total",
                    method=route_key[0],
                    route=route_key[1],
                )
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)
        return await call_next(request)
