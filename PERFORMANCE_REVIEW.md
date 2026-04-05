# Storefront Reviewer — Performance Review (Agent F)

Read-only review of the Phase 2 scaffold. Focus: async correctness, DB efficiency,
Claude API usage, Browser Use / Playwright, worker architecture, frontend hot-paths,
memory, and cold-start.

---

## Backend

### B1. Each DB helper opens and closes its own session (churn + no pooling batch)
- **File:** `src/db/queries.py:107-332` (every function)
- **Observed:** Every query function does `async with AsyncSessionLocal() as session: ... commit()`. The scan worker calls `update_scan` / `insert_finding` many times in sequence, each opening a fresh session and committing a single row.
- **Impact:** For SQLite via `aiosqlite` this means ~N round-trips, N begin/commit pairs, and N fsync-equivalent writes per scan. On an 8-finding scan there are ~12 sequential commits just from `run_scan`. This is wasted wall-clock and the single writer lock serialises everything.
- **Fix:** Accept an optional session arg (unit-of-work) and batch inserts in the worker, e.g. `await session.execute(insert(ScanFinding), [dict,...])` in a single transaction. Alternatively add `list_findings` style bulk-insert helpers.

### B2. `init_db` runs `create_all` on every process boot
- **File:** `src/backend/main.py:44-49`, `src/db/client.py:33-36`
- **Observed:** `lifespan` calls `init_db()` unconditionally, which issues `CREATE TABLE IF NOT EXISTS` for every model on every start.
- **Impact:** Minor (~50–200 ms cold-start in SQLite, more under contention) and it pins the event loop on the synchronous DDL round-trip. For dev it is fine; in any multi-worker deployment this is N workers all racing DDL at boot.
- **Fix:** Gate on an env flag (`AUTO_MIGRATE=1`) or move to a one-shot `scripts/migrate.py` that runs the SQL files in `src/db/migrations/*`.

### B3. `fetch_scan_status` issues two queries where one would do
- **File:** `src/backend/services/scan_service.py:26-39`
- **Observed:** `get_scan` + `count_findings` are two sequential round-trips. Called on every 3-second poll (see F2).
- **Impact:** Doubles the DB cost of the hot polling path. With N concurrent scans being polled, you are doing 2N queries every 3s.
- **Fix:** Add a single query that joins `scans` with `COUNT(scan_findings.id)` grouped by scan_id, or store `findings_count` denormalised on `scans` and increment it inside `insert_finding`.

### B4. `fetch_annotations` + `fetch_competitor_job` also do sequential queries
- **File:** `src/backend/services/scan_service.py:65-75`, `src/backend/services/competitor_service.py:37-51`
- **Observed:** `get_scan` then `list_findings` / `get_competitor_job` then `list_competitor_results`. Not technically N+1, but two serial round-trips where an eager-loaded relationship or `asyncio.gather` would halve latency.
- **Impact:** Small but polls hit these on every tick.
- **Fix:** Run them concurrently with `asyncio.gather(get_scan(id), list_findings(id))`.

### B5. `fetch_page_summary` uses `sync_playwright` in a thread
- **File:** `src/backend/agents/browser_use_runner.py:47-92`
- **Observed:** `_playwright_fetch` uses the sync Playwright API pushed through `asyncio.to_thread`. It launches a fresh Chromium browser, creates a page, navigates, and closes the browser per call.
- **Impact:** Browser launch is ~300–800 ms and a substantial RAM spike (~150 MB). No reuse across calls; no concurrency cap; no enforcement of `max_scan_pages`. Under concurrent scans this will thrash memory and potentially exhaust OS process limits.
- **Fix:** Use `async_playwright` inside the running event loop, keep a single global `Browser` (or a small `asyncio.Semaphore`-bounded pool) that reuses a browser context per scan. Also enforce `settings.max_scan_pages` at the runner level — nothing does today.

### B6. `fetch_page_summary` has no per-scan page-count enforcement
- **File:** `src/backend/agents/browser_use_runner.py:33`, `src/backend/workers/scan_worker.py:131-133`
- **Observed:** `max_pages` is plumbed into `run_scan` but the live path only calls `fetch_page_summary` once (single URL). `settings.max_scan_pages` is defined but never consulted in the worker.
- **Impact:** Feature gap — if scanning is expanded to multi-page crawl, there is no backstop to prevent runaway crawl cost.
- **Fix:** Cap at `min(max_pages, settings.max_scan_pages)` at the top of `run_scan`; pass that budget to the runner.

### B7. `page.evaluate` element-selection returns up to 40 elements via iteration that returns early inside forEach
- **File:** `src/backend/agents/browser_use_runner.py:60-76`
- **Observed:** `if (i > 40) return;` inside `forEach` only skips that single element; the loop continues to the end of the NodeList. On large storefronts (thousands of DOM nodes) that is wasted JS work inside Playwright.
- **Impact:** Minor, but on a heavy page this could add tens of ms.
- **Fix:** Use `Array.from(document.querySelectorAll(sel)).slice(0, 40).forEach(...)` or break with a for loop.

---

## Database

### DB1. Missing index on `reports(parent_id, kind)` composite
- **File:** `src/db/schema.py:113-125`, `src/db/migrations/003_reports.sql:15-16`
- **Observed:** ORM declares `reports` with **no `Index` declarations at all**. The SQL migration defines individual indexes on `parent_id` and `kind`, but since runtime uses `Base.metadata.create_all()` (per the migration file comment), those indexes are **never actually created** at runtime.
- **Impact:** Every `get_report` by PK is fine, but `parent_id` lookups (future join-by-scan/job) will table-scan. More critically, **no indexes declared via ORM exist in the live DB**.
- **Fix:** Add `__table_args__ = (Index("idx_reports_parent_id", "parent_id"), ...)` on every ORM model that needs an index, mirroring the migration SQL. Affects `scans.status`, `scan_findings.scan_id`, `competitor_jobs.status`, `competitor_results.job_id`, `reports.parent_id`, `reports.kind` — **all six indexes are currently missing in the runtime DB**.

### DB2. SQLite without WAL or busy_timeout
- **File:** `src/db/client.py:19-23`
- **Observed:** `create_async_engine` uses defaults. No `connect_args={"timeout": ...}`, no PRAGMA `journal_mode=WAL`, no `synchronous=NORMAL`.
- **Impact:** Under concurrent writes (multiple scans) you will see `database is locked` errors, and every commit does full fsync. WAL roughly doubles write throughput and allows readers concurrent with writers.
- **Fix:** Add an engine `connect` event listener to set `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;` on each connection.

### DB3. `expire_on_commit=False` is good, but session-per-call still forces reconnection
- **File:** `src/db/client.py:25-30`
- **Observed:** aiosqlite session per query call. The async engine does connection pool, but each query opens/closes a session which detaches from the row. Combined with B1 this means every worker tick is a new begin/commit pair.
- **Impact:** Compounds B1.
- **Fix:** See B1 — introduce a session-scoped unit of work for the worker.

### DB4. No transactional boundary around worker steps
- **File:** `src/backend/workers/scan_worker.py:131-168`
- **Observed:** Progress updates and finding inserts are each independent transactions. A crash mid-worker leaves a half-populated scan that a poller reports as "still running" since `status` was not updated.
- **Impact:** Correctness + wasted queries on recovery.
- **Fix:** Single transaction per worker stage; or at least wrap the bulk insert + terminal status in one transaction.

---

## External APIs (Claude / Browser Use)

### C1. Claude SDK is sync-only, dispatched via `asyncio.to_thread`
- **File:** `src/backend/agents/claude_client.py:48-82`
- **Observed:** Uses `anthropic.Anthropic` (sync client) and offloads to a thread. The SDK also offers `AsyncAnthropic`.
- **Impact:** Adds thread-pool overhead, caps parallelism at the default thread pool (usually min(32, cpu*5)). For our workload this is OK, but async-native avoids the GIL hand-off and lets you stream.
- **Fix:** Switch to `anthropic.AsyncAnthropic` and `await client.messages.create(...)`.

### C2. No streaming → full blocking wait for complete response
- **File:** `src/backend/agents/claude_client.py:58-74`
- **Observed:** Uses `messages.create` (non-streaming). Up to 2048 tokens at ~40 tok/s means a 30–50 s hang before the scan can progress.
- **Impact:** Scan latency is dominated by this call. User sees a stalled 35 % → 65 % progress bar for ~30 s.
- **Fix:** Use `messages.stream(...)` and update `progress` incrementally (e.g. parse JSON array items as they arrive and insert findings progressively). Feels dramatically faster.

### C3. Prompt passes raw JSON up to 4 KB of elements, unbounded missing_alt / low_contrast
- **File:** `src/backend/workers/scan_worker.py:137-143`
- **Observed:** `json.dumps(snapshot.get("interactive_elements", []))[:4000]` — slicing a JSON string produces invalid JSON ~100 % of the time when truncated mid-object. Claude then has to parse broken JSON in a system prompt.
- **Impact:** Wasted tokens (broken tail) and degraded model output quality; prompt quality = output quality.
- **Fix:** Truncate the list before `json.dumps` — e.g. `elements[:25]` — and compress to a terse schema (`"{tag}:{selector}:{text_first_40}"`) before serialising.

### C4. No prompt caching, no request caching, no retry/backoff
- **File:** `src/backend/agents/claude_client.py:48-82`
- **Observed:** Every call sends the full system prompt fresh. No Anthropic prompt caching headers (`cache_control`). No retry on 429/503.
- **Impact:** Token waste (~100+ tokens per call for the system prompt), no resilience against transient failures — any hiccup drops you straight to demo mode.
- **Fix:** Use prompt caching for `SYSTEM_SCAN` / `SYSTEM_COMPETITORS`. Add a simple exponential backoff (e.g. tenacity) retrying 2x on 429/5xx.

### C5. No concurrency / rate-limit guardrails on Claude calls
- **File:** `src/backend/workers/scan_worker.py`, `src/backend/workers/competitor_worker.py`
- **Observed:** Each background task constructs its own `ClaudeClient` and fires. Many concurrent scans = many parallel Claude calls.
- **Impact:** Fast path to hitting Anthropic's per-minute rate limits. No backpressure.
- **Fix:** Module-level `asyncio.Semaphore(N)` wrapping `client.complete`.

### C6. `ClaudeClient` not reused across calls
- **File:** `src/backend/workers/scan_worker.py:136`, `src/backend/workers/competitor_worker.py:93`
- **Observed:** Each worker invocation instantiates a new client; `_get_client()` lazily builds an `anthropic.Anthropic()` per instance — that instance creates an `httpx.Client` with its own connection pool.
- **Impact:** No HTTP connection reuse across scans. TLS handshake per scan.
- **Fix:** Module-level singleton `ClaudeClient()`.

---

## Workers

### W1. In-process FastAPI `BackgroundTasks` = no durability, no scaling
- **File:** `src/backend/routes/scan.py:19`, `src/backend/routes/competitors.py:27`
- **Observed:** `background_tasks.add_task(run_scan, ...)` runs on the same event loop as request handling.
- **Impact:** (a) If the server restarts, all in-flight scans are lost with status stuck at "pending"/"running". (b) A burst of scans will starve HTTP handling on the same loop — the event loop does serve the DB + Playwright work. (c) No way to horizontally scale workers.
- **Fix:** For Phase 2 demo this is pragmatic. For production move to a real queue (Redis + arq, RQ, or Celery). At minimum, run a separate Python process that polls "pending" scans from DB, so the API worker stays responsive.

### W2. No timeout around the whole worker
- **File:** `src/backend/workers/scan_worker.py:196-208`
- **Observed:** `run_scan` has no wall-clock budget. If Claude hangs or Playwright stalls, the background task lives forever.
- **Impact:** Memory and connection leak until the process restarts.
- **Fix:** Wrap in `asyncio.wait_for(..., timeout=settings.browser_use_timeout_ms/1000 * 3)`.

### W3. No backpressure / max-concurrent scans
- **File:** entire workers module
- **Observed:** Any caller can spam `POST /scan` and spawn unlimited background tasks.
- **Impact:** Trivially DoS-able; each task holds a Playwright browser + Claude call.
- **Fix:** Global `asyncio.Semaphore` gating `run_scan` entry.

### W4. Small `asyncio.sleep` calls inside demo workers serialise tasks unnecessarily
- **File:** `src/backend/workers/scan_worker.py:111-128`, `src/backend/workers/competitor_worker.py:74-88`
- **Observed:** Artificial sleeps (0.3–0.4 s repeatedly, plus 0.15 s between each competitor insert) to simulate progress.
- **Impact:** Demo-only cost, not a real perf concern, but an 8-finding demo takes ~3s just from sleeps. Acceptable for UX.
- **Fix:** None (intentional).

---

## Frontend

### F1. Polling uses `setTimeout` chain — no cleanup of the in-flight request
- **File:** `src/frontend/web/lib/api.ts:148-176, 179-207`
- **Observed:** `useScanPolling` / `useCompetitorPolling` use `active.current` boolean but do not `AbortController`-cancel the in-flight fetch on unmount. Also the initial `tick()` runs before the `setTimeout(tick, 3000)` — fine, but with `setInterval` semantics you'd get overlapping ticks on slow networks (here `setTimeout` chaining avoids that).
- **Impact:** Minor. On route change the stale fetch completes but `setStatus` short-circuits on `active.current`. Good enough; could leak one request.
- **Fix:** Wire an `AbortController` per tick, abort in cleanup. Also increase interval once `status==="running"` (e.g. exponential: 1s → 3s → 5s).

### F2. Scan page polls every 3 s even after `status==="done"` until it notices
- **File:** `src/frontend/web/lib/api.ts:162`
- **Observed:** Logic returns early when `done|failed`, so it's OK — stops scheduling next tick. Good.

### F3. Annotations fetched only once on mount
- **File:** `src/frontend/web/app/scan/[id]/page.tsx:34-37`
- **Observed:** `getAnnotations(scanId)` runs once on mount. If the scan is still running, findings will never populate until manual refresh.
- **Impact:** UX bug masquerading as perf; user sees `Findings (0)` for a minute.
- **Fix:** Re-fetch annotations whenever `status.progress` changes, or tie to `status.findings_count` growing. Also this means: each poll already returns a count, so only refetch the full list when count changes — avoids wasted bytes.

### F4. Findings list has no virtualization
- **File:** `src/frontend/web/components/FindingsList.tsx:28-35`
- **Observed:** Renders all findings as Cards. Currently capped at 15 in the worker, so fine.
- **Impact:** None at current scale. Would matter if findings grow >100.
- **Fix:** None needed now; consider `react-window` if the cap is lifted.

### F5. Recharts is a heavy dependency for one radar + a few bars
- **File:** `src/frontend/web/package.json:15`, `FlowVisualization.tsx`, `PriceDeltaChart.tsx`
- **Observed:** Recharts + its d3-* deps adds ~130 KB gzipped to the client bundle, loaded on every route.
- **Impact:** Landing page bundle includes chart libs even though charts only show on `/scan/[id]` and `/competitors/[id]`.
- **Fix:** Dynamic-import chart components with `next/dynamic({ ssr: false })` so the chunk is deferred off landing-page JS.

### F6. Landing page is marked `"use client"` implicitly via Link + client components? → actually Server Component
- **File:** `src/frontend/web/app/page.tsx`
- **Observed:** No `"use client"` directive, so it is a Server Component (good). `ScanForm` is likely client.
- **Impact:** Good. Just note `ScanForm` carries its own bundle.

### F7. `getAnnotations` called on mount even while scan is pending
- **File:** `src/frontend/web/app/scan/[id]/page.tsx:34-37`
- **Observed:** Returns 404 until the scan exists; falls back to demo annotations on error (hiding the error). Wasteful network call at t=0.
- **Fix:** Gate on `status?.status === "done"` or `status?.findings_count > 0`.

### F8. `getReport` fires once per change to `status.report_id` — fine, but no caching
- **File:** `src/frontend/web/app/scan/[id]/page.tsx:39-43`
- **Observed:** React state, no react-query, no SWR. OK at this scale.
- **Fix:** Add `swr` if multiple components need the same report.

---

## Memory & Payloads

### M1. Full findings list held in memory for report generation
- **File:** `src/backend/workers/report_generator.py:63-66, 119-120`
- **Observed:** `list_findings` / `list_competitor_results` load entire result sets into Python dicts. Fine at ≤15 items; degrades at scale.
- **Impact:** Not a problem today.
- **Fix:** Streaming aggregation (SQL SUM/GROUP BY) if scaled.

### M2. Playwright returns full `innerText` per element (capped to 80 chars — good)
- **File:** `src/backend/agents/browser_use_runner.py:70`
- **Impact:** Properly capped. No fix needed.

### M3. No image/screenshot capture yet
- **Observed:** Not implemented. If added, streaming upload will be critical.

---

## Cold-Path / Startup

### CS1. Anthropic SDK imported lazily (good) but Playwright imported lazily (good)
- **File:** `claude_client.py:39`, `browser_use_runner.py:49`
- **Impact:** Good — boot stays fast even in demo mode.

### CS2. `create_app()` is called at module import (`app = create_app()`)
- **File:** `src/backend/main.py:79`
- **Observed:** Standard FastAPI pattern.
- **Impact:** Fine.

### CS3. `Settings()` instantiated at import time, blocks on .env read
- **File:** `src/config/settings.py:38`
- **Observed:** Standard pydantic-settings; negligible.

---

## Summary — Top 5 Prioritised Optimisations

| # | Finding | Impact | Effort |
|---|---------|--------|--------|
| 1 | **DB1 — Add missing ORM indexes** (`scan_findings.scan_id`, `scans.status`, `reports.parent_id`, etc. are declared in SQL but never created at runtime because `create_all()` ignores the .sql files) | **Large** — every list/status query will table-scan as data grows; trivial correctness issue masquerading as perf | Low (add `__table_args__` to 6 models) |
| 2 | **C2 + C3 — Stream Claude responses and fix the broken JSON prompt truncation** | **Large** — cuts perceived scan latency from ~45s to ~10s for first findings, plus better model output from well-formed prompt | Medium (switch to `messages.stream`, refactor prompt builder) |
| 3 | **B5 — Reuse one Playwright Browser across scans, run via `async_playwright`** | **Large** — saves ~500 ms + 150 MB per scan; enables real concurrency | Medium (rewrite runner to async + module-level browser singleton) |
| 4 | **B1 + DB2 — Batch inserts per scan inside one transaction + enable SQLite WAL** | **Medium** — halves scan DB time; prevents "database is locked" under concurrency | Low (PRAGMA via event listener, bulk insert helper) |
| 5 | **W1 + W3 — Add concurrency cap on background tasks + worker timeout** | **Medium** — prevents event-loop starvation and runaway scans; real fix is moving to arq/Redis | Low (semaphore + asyncio.wait_for) for now |

### Honourable mentions
- **C4** prompt caching → ~15 % token reduction, trivial to add.
- **B3** denormalise `findings_count` on `scans` → halves polling DB cost.
- **F5** dynamic-import Recharts → ~130 KB off landing bundle.
- **F3/F7** fetch annotations on count-change, not once on mount → fixes the "stuck at 0 findings" UX while also eliminating wasted 404 call.
