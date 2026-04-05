# dropper.ai

A digital storefront reviewer with two functions:
1. **Scan** — Browser Use agent finds a11y/UX issues; Chrome extension highlights them in-page; report with scores + visualizations.
2. **Find Competitors** — Agents scrape similar stores, compare prices/shipping/deals, produce competitor report.

See `build-app.md` for the product spec, `phase1-plan.md` for architecture.

## Prerequisites

- Python 3.12+
- Node 20+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com/)) — or run with `DEMO_MODE=true`
- Browser Use API key ([cloud.browser-use.com](https://cloud.browser-use.com/)) — optional

## Setup

### 1. Environment

```bash
cp .env.example .env
# Fill in real API keys in .env (never commit .env)
```

### 2. Backend (Python + FastAPI + browser-use)

```bash
python3 -m venv .venv
.venv/bin/pip install -r src/backend/requirements.txt
.venv/bin/browser-use install
```

Run:
```bash
.venv/bin/uvicorn src.backend.main:app --reload --port 8000
```

### 3. Frontend website (Next.js)

```bash
cd src/frontend/web
npm install
npm run dev   # http://localhost:3000
```

### 4. Chrome extension

```bash
cd src/frontend/extension
npm install
npm run build          # outputs to dist/
```

Load unpacked: Chrome → `chrome://extensions` → Developer mode → Load unpacked → select `src/frontend/extension/dist`.

### Shortcut

```bash
make install    # one-time
make dev        # runs backend (DEMO_MODE) + web together
```

## Demo mode

Set `DEMO_MODE=true` in `.env` (or inline: `DEMO_MODE=true make backend`) to produce fake findings/competitors without calling Claude or Browser Use. Useful when iterating on the UI.

Workers auto-enter DEMO_MODE when `ANTHROPIC_API_KEY` is empty or the placeholder. Set `DEMO_MODE=true` to force demo mode even with a real key.

## Integration contract

All cross-layer contracts are locked in `CONTRACTS.md`. If you change a pydantic model, a query signature, or an API path, update that file and all three agents (backend / frontend / db).

## Project layout

```
src/
├── backend/    # FastAPI routes, workers, Claude + Browser Use agents
├── frontend/
│   ├── web/    # Next.js app
│   └── extension/  # Chrome MV3 extension
├── config/     # settings, logging, constants
└── db/         # schema, migrations, queries
```

## Phase status

- [x] Phase 1 — Plan & Architect (`phase1-plan.md`)
- [x] Phase 1.5 — Environment + dependencies
- [x] Phase 2 — Parallel build (backend / frontend / db)
- [x] Phase 3 — Integrate
- [ ] Phase 4 — Test
- [ ] Phase 5 — Deploy
- [ ] Phase 6 — Harden
