# Security Audit — Storefront Reviewer

**Auditor:** Agent E (Phase 4)
**Scope:** FastAPI backend, Next.js web frontend, Chrome MV3 extension, SQLite layer, configuration
**Date:** 2026-04-04
**Methodology:** Static review aligned with OWASP Top 10 (2021) plus browser-extension-specific risks. No dynamic testing was performed.

## Executive Summary

The application is a Phase‑2 scaffold with **no authentication, no authorization, and no rate limiting**. It is suitable for local/demo use but must not be exposed to the public internet as-is. The backend accepts arbitrary user-supplied URLs and hands them to a headless browser (Playwright) without any scheme/host validation, creating a clear SSRF path. The Chrome extension requests `<all_urls>` host permissions and ships a content script that embeds backend-sourced data into the DOM — a prompt-injected LLM can thus supply XPath/CSS selectors or text that influence every site the user visits. CORS is configured with `allow_credentials=True` together with a `chrome-extension://*` regex wildcard, which weakens origin isolation.

Database access is correctly parameterized via SQLAlchemy ORM; SQL injection risk is low. Tooltip injection in the extension uses `textContent` for user/LLM-controlled strings (good), but the tooltip scaffold uses a small `innerHTML` template with static strings only (acceptable). No hard-coded secrets were found; `.env` is properly gitignored.

---

## Findings by Severity

### CRITICAL

#### C1. Server-Side Request Forgery (SSRF) via scan URL
**File:** `src/backend/routes/scan.py:14-20`, `src/backend/agents/browser_use_runner.py:33-93`
The `POST /scan` endpoint accepts `ScanRequest.url` (a plain `str` with no validation — see `src/backend/models/scan.py:11`) and passes it verbatim to `page.goto(url, ...)` in Playwright. There is no scheme allow‑list, no host filter for RFC1918 / loopback / link‑local / metadata‑service addresses, and no block on `file://`, `data:`, `javascript:`, or `chrome://` schemes.

**Impact:** An attacker can:
- Probe internal services on the backend host (e.g. `http://127.0.0.1:22`, `http://169.254.169.254/latest/meta-data/` on AWS, `http://localhost:8000/scan` recursively).
- Read local files via `file:///etc/passwd` (Chromium restricts this but historically has bypass CVEs).
- Exfiltrate data: rendered page title/interactive elements are persisted and returned via `GET /annotations/{id}`.
- Trigger cost amplification: any URL becomes a Claude prompt + Playwright session.

**Recommendation:** Switch `ScanRequest.url` to `pydantic.HttpUrl`, then add an explicit guard that (a) requires `http`/`https`, (b) resolves the hostname and rejects private/reserved/loopback/multicast ranges, (c) disallows credentialed URLs, and (d) re-validates after redirects. Apply the same guard to `CompetitorRequest.store_url`.

#### C2. Unauthenticated write + background-job endpoints
**File:** `src/backend/main.py:52-76`, all route files
There is **no authentication middleware, API key, session, or rate limiting** anywhere in the backend. `POST /scan` and `POST /competitors` both enqueue work that consumes Anthropic API tokens and Playwright sessions. `GET /report/{id}`, `GET /scan/{id}`, `GET /annotations/{id}`, `GET /competitors/{id}` expose all historical data to anyone who can guess a UUID (UUIDs are unguessable, but reports are still world-readable given an ID).

**Impact:** Public exposure of the API allows a trivial cost‑bomb DoS against the Anthropic account and Playwright worker pool, plus data exfiltration of any past scan whose ID leaks (referrer headers, browser history, shared URLs).

**Recommendation:** Before any non‑local deployment, add an auth layer (simple API key header for demo, proper OAuth/JWT for production) and per‑IP + per‑key rate limiting (e.g. `slowapi`). Separate read/write endpoints and require auth on the write side at minimum.

---

### HIGH

#### H1. CORS `allow_credentials=True` + wildcard-extension regex
**File:** `src/backend/main.py:58-65`, `src/config/settings.py:23`
Default `CORS_ORIGINS` is `"http://localhost:3000,chrome-extension://*"`. `_parse_cors` converts `chrome-extension://*` to the regex `^chrome-extension://.*$`, and the middleware is configured with `allow_credentials=True` and `allow_methods=["*"]`. Any installed Chrome extension (including malicious ones) can thus make credentialed cross‑origin requests to the API. In plain-HTTP localhost this is low risk, but if the same config is copied to a deployed backend it becomes a cross‑origin data-exfiltration primitive.

**Recommendation:** Since the API has no cookies/sessions today, set `allow_credentials=False` — credentialed mode is unnecessary. For production, pin to the specific published extension ID: `chrome-extension://<your-extension-id>`. Never deploy a `*` regex with credentials enabled.

#### H2. Extension requests `<all_urls>` host permissions and runs on every page
**File:** `src/frontend/extension/manifest.json:24-33`
The extension declares `host_permissions: ["<all_urls>", "http://localhost:8000/*"]` and a content script matching `<all_urls>` at `document_idle`. This means the extension is injected into every tab the user visits, including banking, email, and internal corporate apps. Any vulnerability in `content.ts` (XSS sink, prompt-injected annotations, supply-chain compromise of `react`/`react-dom`) becomes a universal user-compromise vector. No `content_security_policy` is declared, so the extension relies on the MV3 default.

**Recommendation:** Reduce permissions to `activeTab` + `scripting` and inject the content script programmatically via `chrome.scripting.executeScript` only on the user-initiated "Scan this page" action. If `<all_urls>` is required for the MVP, document the threat model and add an explicit `content_security_policy.extension_pages` in the manifest. Also scope `host_permissions` for the backend to the actual deployment origin rather than `http://localhost:8000/*` once deployed.

#### H3. Prompt injection pipeline → attacker-controlled selectors/XPath injected into victim DOM
**Files:** `src/backend/workers/scan_worker.py:144-162`, `src/backend/agents/claude_client.py:48-82`, `src/frontend/extension/src/content.ts:8-95`
The scan worker sends page title + interactive-element text (both attacker-controlled for the scanned URL) to Claude with no sanitization, then blindly persists Claude's JSON output as findings. `selector`, `xpath`, `title`, `description`, and `suggestion` strings round-trip to the Chrome extension's content script, which calls `document.querySelector(f.selector)` and `document.evaluate(f.xpath, ...)` on the **currently active tab** — which may be a completely different origin than the one that was scanned.

While `textContent` is used for tooltip text (good, no XSS), a malicious scanned page can:
- Inject instructions into its visible text that cause Claude to emit CSS selectors targeting password fields on any unrelated site the user overlays.
- Produce huge selectors or pathological XPath that cause denial-of-service on the active tab.
- Emit `bounding_box` coordinates that overlay phishing tooltips on top of legitimate UI (e.g. a fake "Fix: enter your password here" overlay with `pointer-events: auto` and `z-index: 2147483640`).

**Impact:** The overlays are attached to `document.body` with max z-index and `pointer-events: auto`, meaning the attacker controls a full-viewport-clickable overlay on an arbitrary origin.

**Recommendation:**
1. Validate/whitelist selectors server-side (CSS: reject `*`, `>`, combinators referencing `input[type=password]`, length caps; XPath: reject `//` traversal).
2. Restrict annotation injection in the extension to the same origin as the originally scanned URL (compare `location.origin` to the scan's recorded URL origin).
3. Cap tooltip text length (e.g. 400 chars) and strip control characters.
4. Treat all Claude output as untrusted — run it through a strict Pydantic validator with `Literal` enums for severity/category and regex for selectors.

#### H4. No URL validation on `CompetitorRequest.store_url` / custom_prompt
**File:** `src/backend/models/competitor.py:6-9`, `src/backend/routes/competitors.py:23-30`
`store_url` is accepted as `str` and fed into Claude's `COMPETITOR_DISCOVERY_PROMPT` alongside `custom_prompt`, which is completely free-form user input. An attacker can supply a `custom_prompt` instructing Claude to emit different competitor URLs, rationales, or to pivot into any other output. Same SSRF risk applies if live mode later fetches these URLs.

**Recommendation:** Validate `store_url` as `HttpUrl` with public-host check (see C1). Treat `custom_prompt` as data only — wrap it in delimiters and add a system-prompt instruction that the wrapped content is untrusted input, never instructions. Impose a length cap (e.g. 500 chars).

---

### MEDIUM

#### M1. Error messages and LLM output echoed to clients verbatim
**Files:** `src/backend/workers/scan_worker.py:206`, `src/backend/workers/competitor_worker.py:171`, `src/backend/routes/*`
`update_scan(..., error=str(e))` persists raw exception messages which are then returned verbatim via `GET /scan/{id}.error`. For DB / Playwright errors this can leak file paths, DB URLs (`sqlite+aiosqlite:///./storefront.db`), stack-trace fragments, and internal hostnames.

**Recommendation:** Persist a short error code (e.g. `"scan_failed"`) for the API response and log the detailed exception server-side only. Never surface `str(e)` to unauthenticated clients.

#### M2. Extension content script accepts cross-window postMessage without origin check
**File:** `src/frontend/extension/src/content.ts:116-127`
```js
window.addEventListener("message", (ev) => {
  const data = ev.data;
  if (data && data.source === "storefront-reviewer") {
    chrome.runtime.sendMessage(data).catch(() => {});
  }
});
```
`ev.origin` is never checked. Any page the user visits can dispatch `window.postMessage({source:"storefront-reviewer", ...})` and have arbitrary payloads forwarded to the extension's service worker. Currently the background handler ignores unknown `type`s, but if new message types are added later (e.g. `START_SCAN` forwarding) this becomes a CSRF-equivalent into the extension.

**Recommendation:** Check `ev.origin` against an allowlist (your Next.js web UI origin) before forwarding, and also verify `ev.source === window` / `window.top` as appropriate. Define a strict `type` allowlist in the handler.

#### M3. Tooltip uses `innerHTML` for skeleton (low direct risk, brittle)
**File:** `src/frontend/extension/src/content.ts:56-66`
```js
tip.innerHTML = `<div class="sr-tooltip-title"></div>...`;
```
The assigned string is a static literal so there is no immediate XSS, but mixing `innerHTML` with untrusted DOM is a code-smell that invites regressions. If a future developer interpolates `f.title` directly, XSS would fire on every page the user visits.

**Recommendation:** Replace with `document.createElement` + `appendChild` to eliminate the `innerHTML` sink entirely.

#### M4. No max body size / max field length on request models
**Files:** `src/backend/models/scan.py`, `src/backend/models/competitor.py`
Pydantic models accept unbounded strings for `url`, `store_url`, `custom_prompt`, `product_hint`. A 10 MB `custom_prompt` would be stored in SQLite and sent to Claude (cost amplification, DB bloat).

**Recommendation:** Add `Field(..., max_length=2048)` to URL fields and `max_length=1000` to prompts/hints. Configure FastAPI / Uvicorn with a max request-body size (reverse proxy or middleware).

#### M5. `API_HOST=0.0.0.0` as default
**File:** `src/config/settings.py:21`, `.env.example:16`
Default binds to all interfaces. On a developer laptop with an open Wi-Fi, the unauthenticated API is reachable from the LAN. Given there is no auth (C2), this meaningfully increases exposure.

**Recommendation:** Default to `127.0.0.1`; require explicit operator action to bind publicly.

#### M6. Background tasks share the request process; no retry/dead-letter
**File:** `src/backend/routes/scan.py:19`, `src/backend/routes/competitors.py:28`
`BackgroundTasks` runs inline in the Uvicorn worker. A flood of `POST /scan` requests spins up unbounded concurrent Playwright browsers, exhausting memory and providing a cheap DoS vector.

**Recommendation:** Move workers to a real queue (e.g. arq, RQ, Celery) with concurrency bounds, OR gate `POST /scan` behind a semaphore + per-IP rate limit.

---

### LOW

#### L1. UUID-only authorization (IDOR by brute force is hard, but reports are still public-by-ID)
**Files:** all GET routes
Knowing any scan/report/job UUID grants full read. UUID v4 is unguessable, but IDs end up in browser history, referrer headers, and the Next.js URL bar.

**Recommendation:** Bind records to an owner (API key / user) and authorize on read.

#### L2. SQLite `ondelete="CASCADE"` declared but SQLite needs `PRAGMA foreign_keys=ON` per connection
**File:** `src/db/schema.py:54,97`, `src/db/client.py`
aiosqlite does not enable FK enforcement by default. Cascade deletes declared in the schema are not enforced at runtime.

**Recommendation:** Add a connection `PRAGMA foreign_keys=ON` via SQLAlchemy `event.listens_for(engine.sync_engine, "connect")`.

#### L3. Logging configuration never invoked
**File:** `src/config/logging.py`, `src/backend/main.py`
`configure_logging()` is defined but never called from `main.py`. Stdlib `logging.basicConfig` ends up controlling output and `log.exception(...)` calls go through stdlib with default format.

**Recommendation:** Call `configure_logging(settings.log_level)` at app startup.

#### L4. Demo fallback silently swallows real failures
**File:** `src/backend/workers/scan_worker.py:166-168`, `competitor_worker.py:131-133`
Any exception from the live path is converted to demo output and the scan is marked `done`. Operators have no signal that live mode is broken; users get fake findings believing they are real.

**Recommendation:** Set a `degraded=true` flag on the report/scan row and surface it in API responses.

#### L5. `anthropic_api_key` stored as plain string in settings, could leak via `/docs` OpenAPI
**File:** `src/config/settings.py:14`
Not currently exposed on any endpoint, but since FastAPI `/docs` is enabled by default and operators sometimes dump `settings.model_dump()` for debugging, the risk exists.

**Recommendation:** Disable `/docs` in production (`FastAPI(docs_url=None)`), and wrap `anthropic_api_key` in `pydantic.SecretStr`.

#### L6. Recharts / Next.js / React dependencies pinned with `^` (minor-drift)
**Files:** `src/frontend/web/package.json`, `src/frontend/extension/package.json`
No known-abandoned or known-vulnerable packages observed. Versions are all recent (Next 14.2, React 18.3, FastAPI 0.115). Caret ranges mean `npm ci` will pull minor updates. Acceptable for a hackathon scaffold.

**Recommendation:** Run `npm audit` / `pip-audit` in CI before any public deployment; add a lockfile-commit policy.

---

### INFO

#### I1. No CSRF protection on POST endpoints
Not currently needed since the API has no cookies/sessions. If cookie auth is ever added, add CSRF tokens or enforce `SameSite=strict`.

#### I2. Database file lives at `./storefront.db` (CWD-relative)
`DATABASE_URL=sqlite+aiosqlite:///./storefront.db` depends on the backend's working directory. Low risk, but can lead to multiple DB files if workers run from different CWDs.

#### I3. `seed.py` contains plausible-looking but non-real demo data
Scanned: no real credentials or PII observed in `src/db/seed.py`.

#### I4. `.env` correctly gitignored; `.env.example` uses placeholder keys only.
Verified `.gitignore:1-4` covers `.env`, `.env.local`, `*.key`. `.env.example` contains no real secrets.

---

## Prioritized Remediation (Top 5)

1. **Fix SSRF (C1)** — Add `HttpUrl` + private-range/loopback blocklist on `ScanRequest.url` and `CompetitorRequest.store_url` before calling Playwright. Highest real-world impact if deployed.
2. **Add authentication + rate limiting (C2)** — At minimum, an `X-API-Key` middleware plus per-IP rate limits (`slowapi`) on POST endpoints. Required before any non-localhost deployment.
3. **Harden the prompt-injection → overlay pipeline (H3)** — Server-side strict validation of Claude-emitted selectors/xpath/bounding_box; extension-side same-origin check before injecting annotations on the active tab.
4. **Reduce extension host permissions (H2)** — Drop `<all_urls>` host permission and content-script match, use `activeTab` + programmatic injection on user gesture.
5. **Fix CORS credentials+wildcard combination (H1)** — Set `allow_credentials=False` for now, and pin the extension regex to the specific published extension ID before production.

---

## Out of Scope / Not Assessed

- Anthropic/Browser-Use upstream API security
- Supply-chain integrity of npm/PyPI packages (no lockfile audit run)
- TLS configuration / reverse-proxy hardening (no deployment artifacts in repo)
- Secrets management for production (no k8s/terraform yet)
- DOM Clobbering via user-supplied storefront HTML (would apply once Playwright fetches are live)
