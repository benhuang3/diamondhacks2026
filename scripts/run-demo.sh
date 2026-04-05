#!/usr/bin/env bash
# Run the app in DEMO_MODE — no API keys required.
# Workers emit deterministic fake findings/competitors so you can iterate
# on the UI without hitting Claude or Browser Use.
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

VENV_PY="$ROOT_DIR/.venv/bin/python"
VENV_UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

if [[ ! -x "$VENV_UVICORN" ]]; then
  echo "error: .venv not found. Run 'make install' first." >&2
  exit 1
fi

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

# Make sure both children are cleaned up when we exit.
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

LOG_FILE="${LOG_FILE:-logs/backend.log}"
echo "▸ backend (demo)  on http://localhost:$BACKEND_PORT"
echo "                  logs: $LOG_FILE  (warnings also echo to this terminal)"
DEMO_MODE=true \
ANTHROPIC_API_KEY="" \
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
