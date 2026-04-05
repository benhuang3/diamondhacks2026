# Project Structure

Storefront Reviewer — scans e-commerce sites for accessibility/UX issues and
compares pricing across competitors. FastAPI + SQLite backend, Next.js web
UI, and a Chrome extension that overlays findings on live pages.

## Top level

```
.
├── CLAUDE.md              # Agentic workflow playbook (phases 1-6)
├── CONTRACTS.md           # Cross-layer contracts (locked types, env, routes)
├── phase1-plan.md         # Architecture decomposition
├── README.md
├── Makefile
├── .env.example           # Env template (placeholders only)
├── SECURITY_AUDIT.md      # Phase 4 security review output
├── PERFORMANCE_REVIEW.md  # Phase 4 performance review output
└── src/
    ├── backend/           # FastAPI app
    ├── frontend/          # Next.js web app + Chrome extension
    ├── db/                # SQLAlchemy schema, queries, migrations
    └── config/            # Settings, structured logging
```

## Backend — `src/backend/`

FastAPI + async SQLAlchemy (aiosqlite). Background work runs in
`BackgroundTasks` in-process. DEMO_MODE swaps out Claude + browser-use
calls for deterministic fake data.

```
backend/
├── main.py                # create_app(), lifespan, middleware wiring
├── routes/                # HTTP endpoints (thin; delegate to services)
│   ├── scan.py            #   POST /scan, GET /scan/{id}
│   ├── annotations.py     #   GET /annotations/{scan_id}
│   ├── competitors.py     #   POST /competitors, GET /competitors/{id}
│   └── reports.py         #   GET /report/{id}
├── services/              # DB-facing business logic
│   ├── scan_service.py
│   └── competitor_service.py
├── workers/               # Long-running jobs (scheduled via BackgroundTasks)
│   ├── scan_worker.py     #   run_scan() — demo + live paths
│   ├── competitor_worker.py
│   └── report_generator.py
├── agents/                # LLM + browser integrations
│   ├── claude_client.py   #   thin async wrapper around anthropic SDK
│   ├── browser_use_runner.py
│   ├── accessibility_prompts.py
│   └── competitor_prompts.py
├── models/                # Pydantic request/response schemas
│   ├── scan.py            #   ScanRequest validates URL via SSRF guard
│   ├── competitor.py      #   CompetitorRequest validates + sanitizes
│   │                      #   custom_prompt / product_hint as untrusted
│   └── report.py
├── middleware/
│   ├── rate_limit.py      #   Per-IP sliding-window limiter, LRU-bounded bucket
│   │                      #   map, opt-in X-Forwarded-For trust
│   └── request_context.py #   X-Request-ID (charset-restricted) + structlog
│                          #   binding + access log
├── security/
│   └── url_guard.py       #   SSRF: scheme + IP-literal blocklist (unwraps
│                          #   IPv4-mapped/6to4/teredo v6), async DNS check,
│                          #   and a process-wide getaddrinfo egress guard
├── observability/
│   └── metrics.py         #   In-process counters, Prometheus exposition
└── tests/                 # pytest (46 tests) — fixtures in conftest.py
    ├── test_db_queries.py
    ├── test_services.py
    ├── test_routes.py
    ├── test_claude_client.py
    └── test_workers.py
```

### Request flow

```
Client → CORS (credentials:off) → RateLimitMiddleware → RequestContextMiddleware
      → FastAPI route → Pydantic (SSRF URL guard) → service
      → queries.py (SQLAlchemy) → SQLite (WAL)
                                 ↓
                          BackgroundTasks → worker (scan/competitor)
                                          → Claude + browser_use → DB
```

Any DNS resolution inside the worker process is filtered by a global
``socket.getaddrinfo`` wrapper (installed in lifespan) so DNS rebinding
and redirect-based SSRF pivots can't reach private ranges.

## Frontend — `src/frontend/web/`

Next.js 14 App Router + Tailwind + shadcn-style UI primitives. Polls the
backend via `lib/api.ts`; falls back to fixtures in `lib/demo-data.ts` when
the API is unreachable.

```
web/
├── app/                   # App Router pages
│   ├── page.tsx           #   Landing — submit scan/competitor job
│   ├── scan/[id]/page.tsx #   Scan progress + findings + report
│   ├── competitors/page.tsx
│   ├── competitors/[id]/page.tsx
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── ScanForm.tsx, CompetitorForm.tsx
│   ├── FindingsList.tsx, FlowVisualization.tsx
│   ├── ScoreCard.tsx, PriceDeltaChart.tsx
│   └── ui/                #   button, card, badge, input, progress
├── lib/
│   ├── api.ts             #   safeFetch + useScanPolling/useCompetitorPolling
│   ├── types.ts           #   mirrors backend Pydantic models
│   ├── demo-data.ts       #   offline fallback fixtures
│   └── utils.ts
└── package.json, tsconfig.json, tailwind.config.ts, next.config.js
```

## Chrome extension — `src/frontend/extension/`

Manifest v3. The content script draws an overlay of findings from the
backend on whatever tab is active.

```
extension/
├── manifest.json
├── src/
│   ├── background.ts
│   ├── content.ts         #   injects overlays from /annotations/{id}
│   ├── popup.tsx
│   ├── popup.html
│   ├── overlay.css
│   └── types.ts
├── scripts/make-icons.mjs
└── vite.config.ts
```

## Database — `src/db/`

SQLite via `sqlite+aiosqlite`. Runtime uses `Base.metadata.create_all()`
from the SQLAlchemy models; the `.sql` files under `migrations/` mirror the
same schema as reference docs.

```
db/
├── schema.py              # ORM models + Index definitions
├── queries.py             # typed query functions (no raw SQL). Includes
│                          # insert_findings_bulk() for single-txn batches.
├── client.py              # async engine + session factory; init_db() sets
│                          # WAL + synchronous=NORMAL + foreign_keys=ON
├── seed.py
└── migrations/
    ├── 001_init.sql             #   scans, scan_findings
    ├── 002_competitors.sql      #   competitor_jobs, competitor_results
    └── 003_reports.sql          #   reports
```

Tables: `scans`, `scan_findings`, `competitor_jobs`, `competitor_results`,
`reports`. All list/lookup columns are indexed.

## Config — `src/config/`

```
config/
├── settings.py            # pydantic-settings, reads .env
├── logging.py             # structlog JSON + stdlib integration
└── constants.py
```

Settings are environment-driven (`.env` → `settings`). Notable knobs:
`DEMO_MODE`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `CORS_ORIGINS`,
`MAX_SCAN_PAGES`, `MAX_COMPETITORS`, `RATE_LIMIT_SCAN_PER_MIN`,
`RATE_LIMIT_MAX_BUCKETS`, `TRUST_FORWARDED_FOR`, `SSRF_EGRESS_GUARD`.

## Observability

- **Logs** — JSON via structlog; every line carries `request_id` bound by
  `RequestContextMiddleware`.
- **Metrics** — `GET /metrics` exposes Prometheus text:
  `http_requests_total`, `http_rate_limited_total`, `scans_*_total`,
  `competitor_jobs_*_total`, `claude_calls_total`,
  `claude_call_failures_total`, `ssrf_rejections_total`.
- **Request IDs** — inbound `X-Request-ID` honored only if it matches
  `^[A-Za-z0-9_-]{1,128}$`; otherwise a fresh id is generated. Echoed
  back on every response as `X-Request-ID`.

## Running

```
# backend
cd src/backend && uvicorn main:app --reload
# or demo mode
DEMO_MODE=true uvicorn src.backend.main:app --reload

# tests
pytest src/backend/tests/

# web UI
cd src/frontend/web && npm run dev

# extension
cd src/frontend/extension && npm run build
```
