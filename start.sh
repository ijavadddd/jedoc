#!/usr/bin/env bash
# Start the Jedoc API and the Vite workstation. Both bind to localhost.
# Live Cursor runs need the host `agent` CLI on PATH — prefer this over Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_PORT="${JEDOC_API_PORT:-8000}"
UI_PORT="${JEDOC_UI_PORT:-5173}"
export JEDOC_API_PROXY="${JEDOC_API_PROXY:-http://127.0.0.1:${API_PORT}}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

if [[ ! -d frontend/node_modules ]]; then
  npm --prefix frontend install
fi
mkdir -p data

cleanup() {
  if [[ -n "${BACK_PID:-}" ]]; then
    kill "$BACK_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONT_PID:-}" ]]; then
    kill "$FRONT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Stale uvicorn workers keep data/checkpoints.sqlite locked even after losing the port —
# Resume then hangs forever with status=running and no agent output.
pkill -f "uvicorn backend.api.server:app" 2>/dev/null || true
sleep 0.4
free_listen_port() {
  local port="$1"
  local pids
  pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Stopping process on port ${port}: ${pids}"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.4
    pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}
free_listen_port "$API_PORT"

python -m uvicorn backend.api.server:app --host 127.0.0.1 --port "$API_PORT" &
BACK_PID=$!
npm --prefix frontend run dev -- --hostname 127.0.0.1 --port "$UI_PORT" &
FRONT_PID=$!

echo "Jedoc API  http://127.0.0.1:${API_PORT}"
echo "Jedoc UI   http://127.0.0.1:${UI_PORT}"
if ! command -v agent >/dev/null 2>&1; then
  echo "warning: agent is not on PATH — Providers/Models will be empty until you install the Cursor CLI"
fi
wait -n "$BACK_PID" "$FRONT_PID"
