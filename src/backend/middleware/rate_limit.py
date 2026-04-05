"""In-process sliding-window rate limiter.

Keyed on ``(method, path, client_ip)``. Intended for expensive endpoints
that spawn background jobs (Claude + BrowserUse). A real deployment should
front this with an edge limiter; this middleware is a cost-bomb backstop.

Memory is bounded by an LRU cap on the bucket map so a flood of distinct
source IPs can't grow ``_hits`` without limit.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
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
        *,
        max_buckets: int = 10_000,
        trust_forwarded_for: bool = False,
    ) -> None:
        """
        Args:
            rules: ``{(METHOD, path): (max_requests, window_seconds)}``.
                Only exact matches are rate-limited; everything else passes
                through.
            max_buckets: upper bound on distinct client buckets retained.
                When exceeded, the least-recently-touched bucket is evicted.
            trust_forwarded_for: use the left-most X-Forwarded-For entry as
                the client IP. Only enable behind a trusted reverse proxy.
        """
        super().__init__(app)
        self._rules = rules
        self._max_buckets = max_buckets
        self._trust_xff = trust_forwarded_for
        self._hits: OrderedDict[tuple[str, str, str], Deque[float]] = OrderedDict()

    def _client_ip(self, request: Request) -> str:
        if self._trust_xff:
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                # left-most entry is the original client per RFC 7239 custom
                first = xff.split(",")[0].strip()
                if first:
                    return first
        return request.client.host if request.client else "unknown"

    def _get_bucket(self, key: tuple[str, str, str]) -> Deque[float]:
        bucket = self._hits.get(key)
        if bucket is None:
            bucket = deque()
            self._hits[key] = bucket
            # Evict oldest once we blow past the cap.
            while len(self._hits) > self._max_buckets:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)
        return bucket

    async def dispatch(self, request: Request, call_next):
        route_key = (request.method.upper(), request.url.path)
        rule = self._rules.get(route_key)
        if rule is not None:
            max_req, window = rule
            client_ip = self._client_ip(request)
            bucket_key = (route_key[0], route_key[1], client_ip)
            now = time.monotonic()
            bucket = self._get_bucket(bucket_key)
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
            # Drop empty buckets to keep memory lean even below the cap.
            if not bucket:
                self._hits.pop(bucket_key, None)
        return await call_next(request)
