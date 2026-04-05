"""FastAPI entrypoint for the dropper.ai backend."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from src.config.logging import configure_logging
from src.config.settings import settings
from src.db.client import init_db

from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_context import RequestContextMiddleware
from .observability.metrics import metrics
from .routes.annotations import router as annotations_router
from .routes.competitors import router as competitors_router
from .routes.reports import router as reports_router
from .routes.scan import router as scan_router
from .security.url_guard import install_egress_guard

log = logging.getLogger(__name__)


def _parse_cors(origins_raw: str) -> tuple[list[str], list[str]]:
    """Split a comma-separated origins string into (exact_origins, regexes).

    `chrome-extension://*` becomes a regex; others are exact.
    """
    exact: list[str] = []
    regexes: list[str] = []
    for o in (origins_raw or "").split(","):
        o = o.strip()
        if not o:
            continue
        if "*" in o:
            # convert glob-ish to regex
            pat = re.escape(o).replace(r"\*", ".*")
            regexes.append(f"^{pat}$")
        else:
            exact.append(o)
    return exact, regexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(
        settings.log_level,
        log_file=settings.log_file,
        log_file_max_bytes=settings.log_file_max_bytes,
        log_file_backup_count=settings.log_file_backup_count,
    )
    if settings.ssrf_egress_guard:
        install_egress_guard()
    try:
        await init_db()
    except Exception as e:  # noqa: BLE001
        log.exception("init_db failed at startup: %s", e)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="dropper.ai", version="0.1.0", lifespan=lifespan)

    exact_origins, regex_origins = _parse_cors(settings.cors_origins)
    allow_origin_regex = "|".join(regex_origins) if regex_origins else None

    # Middleware order matters — Starlette wraps in reverse add_middleware
    # order, so the LAST add is OUTERMOST. We want the stack to be:
    #   RequestContext (outermost, logs every request)
    #     CORSMiddleware (adds Access-Control-* headers, including on 429s)
    #       RateLimitMiddleware
    #         route
    # So we add in inside-out order: rate-limit first, CORS next, request
    # context last. This guarantees 429 responses carry CORS headers so
    # the browser can read the status instead of "Failed to fetch".
    app.add_middleware(
        RateLimitMiddleware,
        rules={
            ("POST", "/scan"): (settings.rate_limit_scan_per_min, 60),
            ("POST", "/competitors"): (settings.rate_limit_competitors_per_min, 60),
        },
        max_buckets=settings.rate_limit_max_buckets,
        trust_forwarded_for=settings.trust_forwarded_for,
    )
    # The app is cookie-less and uses no browser-auth credentials, so we
    # disable allow_credentials. This neutralizes the ``chrome-extension://.*``
    # regex, since credentialed cross-origin requests are what made that
    # wildcard dangerous in the first place.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=exact_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint() -> str:
        return metrics.render_prometheus()

    app.include_router(scan_router)
    app.include_router(competitors_router)
    app.include_router(annotations_router)
    app.include_router(reports_router)

    return app


app = create_app()
