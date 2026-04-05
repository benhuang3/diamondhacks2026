#!/usr/bin/env bash
# Run the app in LIVE mode — real Claude + (optional) Browser Use calls.
# Requires .env with ANTHROPIC_API_KEY set. BROWSER_USE_API_KEY is optional;
# the browser_use integration falls back gracefully if unset.
#
# Starts:
#   - FastAPI backend on http://localhost:8000
#   - Next.js web UI on http://localhost:3000 (Next dev HMR)
#   - Chrome extension watch rebuild into src/frontend/extension/dist
#
# Ctrl-C stops all three.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

VENV_UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

if [[ ! -x "$VENV_UVICORN" ]]; then
  echo "error: .venv not found. Run 'make install' first." >&2
  exit 1
fi

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "error: .env not found. Copy .env.example to .env and fill in keys." >&2
  exit 1
fi

# Load .env into this shell so we can validate required keys + the children
# inherit them. Direct source (process substitution drops values here).
set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env"
set +a

if [[ -z "${ANTHROPIC_API_KEY:-}" ]] \
   || [[ "$ANTHROPIC_API_KEY" == "your-anthropic-api-key-here" ]] \
   || [[ "$ANTHROPIC_API_KEY" == sk-ant-xxxxx* ]]; then
  echo "error: ANTHROPIC_API_KEY is missing or a placeholder in .env." >&2
  echo "       get one at https://console.anthropic.com/" >&2
  exit 1
fi

# Force live mode even if the file has DEMO_MODE=true lingering.
export DEMO_MODE=false

if [[ ! -d "$ROOT_DIR/src/frontend/web/node_modules" ]]; then
  echo "error: src/frontend/web/node_modules missing. Run 'make install' first." >&2
  exit 1
fi

if [[ ! -d "$ROOT_DIR/src/frontend/extension/node_modules" ]]; then
  echo "error: src/frontend/extension/node_modules missing. Run 'make install' first." >&2
  exit 1
fi

check_port() {
  local port="$1" label="$2"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "error: port $port ($label) is already in use." >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    echo "hint: kill the process or set ${label^^}_PORT=..." >&2
    exit 1
  fi
}
check_port "$BACKEND_PORT" backend
check_port "$WEB_PORT" web

pids=()
cleanup() {
  echo
  echo "stopping..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "▸ backend (live)  on http://localhost:$BACKEND_PORT  (model=${ANTHROPIC_MODEL:-claude-opus-4-6})"
"$VENV_UVICORN" src.backend.main:app \
  --reload --host 127.0.0.1 --port "$BACKEND_PORT" &
pids+=("$!")

echo "▸ web             on http://localhost:$WEB_PORT"
( cd src/frontend/web && \
  NEXT_PUBLIC_API_BASE_URL="http://localhost:$BACKEND_PORT" \
  npm run dev -- -p "$WEB_PORT" ) &
pids+=("$!")

echo "▸ extension       rebuilding to src/frontend/extension/dist (watch)"
( cd src/frontend/extension && npm run dev ) &
pids+=("$!")

echo
echo "▸ load extension: chrome://extensions → Load unpacked → src/frontend/extension/dist"
echo "▸ after extension edits: click the ⟳ icon on the extension card"
echo "▸ press Ctrl-C to stop all three"
wait
