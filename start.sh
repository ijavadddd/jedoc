#!/usr/bin/env bash
# Start the Jedoc API and the Vite workstation. Both bind to localhost.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

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

python -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8000 &
BACK_PID=$!
npm --prefix frontend run dev -- --hostname 127.0.0.1 --port 5173 &
FRONT_PID=$!

echo "Jedoc API  http://127.0.0.1:8000"
echo "Jedoc UI   http://127.0.0.1:5173"
wait -n "$BACK_PID" "$FRONT_PID"
