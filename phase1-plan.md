# Phase 1 Plan: Storefront Reviewer

## 1. Architecture Diagram

```
┌─────────────────────┐         ┌──────────────────────┐
│  Chrome Extension   │◄───────►│  Website Frontend    │
│  (MV3, TypeScript)  │ window  │  (Next.js on Vercel) │
│  - popup.tsx        │ message │  - /scan wizard      │
│  - content.ts       │         │  - /report/:id       │
│  - background.ts    │         │  - /competitors/:id  │
└──────────┬──────────┘         └──────────┬───────────┘
           │                               │
           │  fetch annotations            │  REST (JSON, poll 2-5s)
           ▼                               ▼
┌──────────────────────────────────────────────────────┐
│          FastAPI Backend (Modal/Railway)             │
│  routes: /scan  /scan/{id}  /competitors             │
│          /competitors/{id}  /annotations/{id}        │
│          /report/{id}                                │
│  workers: asyncio background tasks                   │
└───────┬────────────────┬────────────────┬────────────┘
        │                │                │
        ▼                ▼                ▼
┌───────────────┐ ┌──────────────┐ ┌──────────────────┐
│  Browser Use  │ │  Anthropic   │ │  Supabase /      │
│  workers      │ │  Claude SDK  │ │  Postgres        │
│  (Playwright) │ │  (analysis + │ │  scans,          │
│  - scan pages │ │   report gen)│ │  findings,       │
│  - crawl      │ │              │ │  competitors,    │
│    competitors│ │              │ │  reports         │
└───────────────┘ └──────────────┘ └──────────────────┘

SCAN FLOW:
  Extension/UI → POST /scan {url} → DB insert scan(pending)
    → async worker: BrowserUse navigates url, collects DOM snapshots, a11y tree
    → Claude analyzes → writes scan_findings rows (selector, issue, severity)
    → Claude generates report → reports row
    → status=done
  Extension polls GET /annotations/{scan_id} → injects highlights via content.ts
  Frontend polls GET /scan/{id} → renders report + charts

COMPETITOR FLOW:
  UI → POST /competitors {url, optional_prompt} → competitor_jobs(pending)
    → async worker: Claude proposes competitor URLs
    → BrowserUse visits each, extracts price/shipping/tax/deals (+ checkout attempt)
    → writes competitor_results rows
    → Claude generates comparison report → reports row
    → status=done
  Frontend polls GET /competitors/{id} → renders deltas + recommendations
```

---

## 2. File Tree

```
src/
├── backend/                                    [Agent A]
│   ├── main.py                                 # FastAPI app, CORS, router mount
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── scan.py                             # POST /scan, GET /scan/{id}
│   │   ├── competitors.py                      # POST /competitors, GET /competitors/{id}
│   │   ├── annotations.py                      # GET /annotations/{scan_id}  (extension)
│   │   └── reports.py                          # GET /report/{id}
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── scan_worker.py                      # BrowserUse scan + findings
│   │   ├── competitor_worker.py                # BrowserUse competitor crawl
│   │   └── report_generator.py                 # Claude report synthesis
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── claude_client.py                    # Anthropic SDK wrapper
│   │   ├── browser_use_runner.py               # BrowserUse session helpers
│   │   ├── accessibility_prompts.py            # prompt templates for scan
│   │   └── competitor_prompts.py               # prompt templates for competitors
│   ├── models/
│   │   ├── __init__.py
│   │   ├── scan.py                             # pydantic: ScanRequest, ScanStatus, ScanFinding
│   │   ├── competitor.py                       # pydantic: CompetitorRequest, CompetitorResult
│   │   └── report.py                           # pydantic: Report, ReportSection
│   ├── services/
│   │   ├── __init__.py
│   │   ├── scan_service.py                     # business logic, DB calls
│   │   └── competitor_service.py
│   └── requirements.txt
│
├── frontend/                                   [Agent B]
│   ├── web/                                    # Next.js app
│   │   ├── package.json
│   │   ├── next.config.js
│   │   ├── tailwind.config.ts
│   │   ├── tsconfig.json
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx                        # landing: paste URL, start scan
│   │   │   ├── scan/[id]/page.tsx              # scan report view
│   │   │   ├── competitors/page.tsx            # start competitor job
│   │   │   └── competitors/[id]/page.tsx       # competitor report
│   │   ├── components/
│   │   │   ├── ui/                             # shadcn primitives (button, card, etc.)
│   │   │   ├── ScanForm.tsx
│   │   │   ├── CompetitorForm.tsx
│   │   │   ├── FindingsList.tsx
│   │   │   ├── ScoreCard.tsx
│   │   │   ├── FlowVisualization.tsx           # Recharts
│   │   │   └── PriceDeltaChart.tsx
│   │   └── lib/
│   │       ├── api.ts                          # fetch wrappers + polling
│   │       └── types.ts                        # mirrors backend pydantic shapes
│   └── extension/                              # Chrome MV3
│       ├── manifest.json
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts                      # build config
│       ├── src/
│       │   ├── background.ts                   # service worker, API calls
│       │   ├── content.ts                      # DOM injection, highlight overlays
│       │   ├── popup.tsx                       # popup UI (scan, view findings)
│       │   ├── popup.html
│       │   ├── overlay.css                     # highlight styles
│       │   └── types.ts                        # shared annotation types
│       └── icons/
│           ├── icon16.png
│           ├── icon48.png
│           └── icon128.png
│
├── config/                                     [Agent C]
│   ├── __init__.py
│   ├── settings.py                             # pydantic-settings, env loading
│   ├── logging.py                              # structured logging
│   └── constants.py                            # severity levels, timeouts
│
└── db/                                         [Agent C]
    ├── __init__.py
    ├── client.py                               # supabase/asyncpg client factory
    ├── schema.py                               # SQLAlchemy/Pydantic table defs
    ├── queries.py                              # repo pattern: insert/select helpers
    ├── seed.py                                 # demo data
    └── migrations/
        ├── 001_init.sql                        # scans, scan_findings
        ├── 002_competitors.sql                 # competitor_jobs, competitor_results
        └── 003_reports.sql                     # reports

.env.example                                    [Agent C]
docker-compose.yml                              [Agent C, optional]
```

---

## 3. API Contracts

All responses JSON. Backend base URL configured via `NEXT_PUBLIC_API_BASE_URL` and extension `API_BASE_URL`.

### POST /scan
Start a scan.
- Request: `{ "url": "https://store.example.com", "max_pages": 5 }`
- Response 202: `{ "scan_id": "uuid", "status": "pending" }`

### GET /scan/{scan_id}
Poll scan status/result.
- Response 200:
```json
{
  "scan_id": "uuid",
  "status": "pending|running|done|failed",
  "progress": 0.42,
  "url": "https://...",
  "findings_count": 12,
  "report_id": "uuid|null",
  "error": null
}
```

### GET /annotations/{scan_id}
Used by extension content script to inject highlights.
- Response 200:
```json
{
  "scan_id": "uuid",
  "url": "https://...",
  "annotations": [
    {
      "id": "uuid",
      "selector": "button.checkout",
      "xpath": "/html/body/...",
      "bounding_box": {"x":0,"y":0,"w":0,"h":0},
      "severity": "high|medium|low",
      "category": "a11y|ux|contrast|nav",
      "title": "Low contrast CTA",
      "description": "...",
      "suggestion": "..."
    }
  ]
}
```

### POST /competitors
- Request: `{ "store_url": "https://...", "custom_prompt": "optional", "product_hint": "optional" }`
- Response 202: `{ "job_id": "uuid", "status": "pending" }`

### GET /competitors/{job_id}
- Response 200:
```json
{
  "job_id": "uuid",
  "status": "pending|running|done|failed",
  "progress": 0.6,
  "competitors": [
    {
      "name": "string",
      "url": "https://...",
      "price": 29.99,
      "shipping": 4.99,
      "tax": 2.4,
      "discount": "SAVE10",
      "checkout_total": 37.38,
      "notes": "..."
    }
  ],
  "report_id": "uuid|null"
}
```

### GET /report/{report_id}
- Response 200:
```json
{
  "report_id": "uuid",
  "kind": "scan|competitors",
  "scores": {"accessibility":72,"ux":65,"flow":80},
  "summary": "markdown string",
  "sections": [{"title":"...","body":"markdown","chart":{...}}],
  "recommendations": ["..."]
}
```

### GET /health
- Response: `{"status":"ok"}`

---

## 4. Database Schema

**scans**
- id (uuid pk), url (text), status (text: pending/running/done/failed), progress (float), max_pages (int), report_id (uuid fk nullable), error (text nullable), created_at, updated_at

**scan_findings**
- id (uuid pk), scan_id (uuid fk → scans), selector (text), xpath (text), bounding_box (jsonb), severity (text), category (text), title (text), description (text), suggestion (text), page_url (text), created_at

**competitor_jobs**
- id (uuid pk), store_url (text), custom_prompt (text nullable), product_hint (text nullable), status (text), progress (float), report_id (uuid fk nullable), error (text nullable), created_at, updated_at

**competitor_results**
- id (uuid pk), job_id (uuid fk → competitor_jobs), name (text), url (text), price (numeric), shipping (numeric), tax (numeric), discount (text nullable), checkout_total (numeric nullable), raw_data (jsonb), notes (text), created_at

**reports**
- id (uuid pk), kind (text: scan/competitors), parent_id (uuid — scan_id or job_id), scores (jsonb), summary (text), sections (jsonb), recommendations (jsonb), created_at

Relationships: scans 1→N scan_findings; competitor_jobs 1→N competitor_results; scans/competitor_jobs 1→1 reports via report_id.

---

## 5. Chrome Extension Contract

**Handshake & lifecycle:**
1. User clicks extension icon → `popup.tsx` shows current tab URL + "Scan this page" button.
2. Popup sends message `{type:"START_SCAN", url}` to `background.ts`.
3. Background calls `POST /scan`, stores `scan_id` in `chrome.storage.local`, polls `GET /scan/{id}` every 3s.
4. When status=done, background fetches `GET /annotations/{scan_id}` and sends `{type:"INJECT_ANNOTATIONS", annotations}` to the active tab's content script.
5. `content.ts` receives message, resolves each `selector` (fallback xpath), wraps matched elements in `<div class="sr-highlight sr-sev-{severity}">` overlays, attaches tooltips with title/description/suggestion.
6. Clearing: popup sends `{type:"CLEAR_ANNOTATIONS"}` → content script removes overlays.

**Message passing:**
- popup ↔ background: `chrome.runtime.sendMessage`
- background ↔ content: `chrome.tabs.sendMessage`
- content listens via `chrome.runtime.onMessage`

**Website frontend ↔ extension handshake:**
- Frontend can deep-link to extension via `window.postMessage({source:"storefront-reviewer", type:"OPEN_SCAN", scan_id})`.
- Content script listens for `storefront-reviewer` origin messages and forwards to background.
- Alternative simpler path: frontend shows scan_id, user pastes into extension popup.

**Annotation contract (locked):** see GET /annotations response above. Extension consumes `selector` first, falls back to `xpath`, uses `bounding_box` as last resort for absolute-positioned overlay.

**manifest.json permissions:** `activeTab`, `scripting`, `storage`, host permissions `<all_urls>`.

---

## 6. Task Decomposition (Phase 2, parallel)

### Agent A — Backend (`src/backend/**`)
1. Scaffold `main.py`, CORS, health route.
2. Define pydantic models in `models/` (depends on: locked contracts §7).
3. Implement `routes/scan.py` endpoints with in-memory stub first, then DB (depends on: C-3).
4. Implement `routes/competitors.py`, `routes/annotations.py`, `routes/reports.py`.
5. Implement `agents/claude_client.py` + prompt templates.
6. Implement `agents/browser_use_runner.py`.
7. Implement `workers/scan_worker.py` — DOM crawl + Claude a11y analysis → findings.
8. Implement `workers/competitor_worker.py` — URL discovery + price extraction.
9. Implement `workers/report_generator.py` — score + sections.
10. Wire asyncio background tasks via FastAPI `BackgroundTasks`.

### Agent B — Frontend + Extension (`src/frontend/**`)
1. Scaffold Next.js + Tailwind + shadcn (`web/`).
2. Build `lib/types.ts` mirroring backend models (depends on: locked contracts §7).
3. Build `lib/api.ts` fetch wrappers + 3s polling hook.
4. Build `ScanForm`, `app/page.tsx`, `app/scan/[id]/page.tsx`.
5. Build `FindingsList`, `ScoreCard`, `FlowVisualization` (Recharts).
6. Build `CompetitorForm`, competitor pages, `PriceDeltaChart`.
7. Scaffold extension `manifest.json` + Vite build.
8. Implement `background.ts` (API polling), `content.ts` (DOM injection), `popup.tsx`.
9. Implement `overlay.css` + severity colors.
10. Wire extension ↔ frontend postMessage handshake.

### Agent C — Config + DB (`src/config/**`, `src/db/**`)
1. Write `.env.example` with all keys.
2. `config/settings.py` pydantic-settings loader.
3. `db/migrations/001_init.sql`, `002_competitors.sql`, `003_reports.sql` (depends on: schema §4).
4. `db/client.py` — supabase/asyncpg factory.
5. `db/queries.py` — insert/update/select helpers (depends on: backend models §7).
6. `db/seed.py` — demo scan + findings for offline demo fallback.
7. `config/logging.py` structured logs.
8. `config/constants.py` — severity enum, timeouts.

**Cross-agent dependencies:** A-2 & B-2 & C-5 all depend on contracts locked in §7. A-3/4 depend on C-4. B-8 depends on annotation contract.

---

## 7. Critical Contracts to Lock Before Phase 2

1. **`ScanFinding` shape** — exact JSON keys (id, selector, xpath, bounding_box, severity, category, title, description, suggestion). Used by backend DB, API response, frontend display, extension injection.
2. **`Annotation` payload for extension** — `GET /annotations/{scan_id}` response structure (see §3). Extension and backend must agree on selector/xpath fallback order.
3. **Status enum** — `pending | running | done | failed` used across scans + competitor_jobs. No variants.
4. **Env variable names** — `ANTHROPIC_API_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY`, `API_BASE_URL`, `NEXT_PUBLIC_API_BASE_URL`, `BROWSER_USE_HEADLESS`.
5. **Report shape** — `scores` object keys (`accessibility`, `ux`, `flow` for scan; `pricing`, `value`, `experience` for competitors), `sections[]` structure.

---

## 8. Risks & Open Questions

**Risks:**
- **Browser Use reliability on arbitrary storefronts** — many stores block headless browsers (Cloudflare, bot detection). Mitigation: bundle 2-3 pre-recorded demo scans for fallback, seed DB with them.
- **Selector stability** — CSS selectors drift between page loads on SPA stores. Mitigation: capture xpath + bounding_box as fallbacks, snapshot HTML at scan time.
- **Checkout flow attempts** — actually checking out on competitor sites risks real charges, CAPTCHAs, account bans. Mitigation: stop at cart/shipping calculation step, never submit payment.
- **Claude token/cost budget** — full DOM analysis can blow context. Mitigation: pre-filter DOM to interactive elements + a11y tree only.
- **Extension ↔ website CORS** — extension content script on arbitrary origins fetching localhost:8000 needs host_permissions set correctly.
- **Polling latency** — 2-5s polls + BrowserUse crawl = scan may take 30-120s; demo must account for this (pre-seeded results recommended).

**Open questions for user:**
1. Which sponsor is primary? Stack guidance says Anthropic Claude — is Anthropic the primary sponsor track? This affects depth of integration (tool use vs chat).
2. Auth required, or single-user demo? Plan assumes no auth.
3. Should extension work on any storefront or only demo-whitelisted domains?
4. Real checkout attempts, or stop at cart? (Plan assumes stop at cart.)
5. Target storefronts: Shopify-generic, Amazon-style, or specific verticals (fashion, electronics)?
6. Visualization library preference — Recharts assumed.
7. Deployment: Modal vs Railway for FastAPI? BrowserUse needs Playwright, may need custom container.
