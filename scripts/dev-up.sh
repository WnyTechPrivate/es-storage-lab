#!/usr/bin/env bash
# Linux / macOS / WSL: start backend (8766) + frontend dev (5173) in this shell
# Usage:  ./scripts/dev-up.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  echo "stopping..."
  kill ${BACK_PID:-} ${FRONT_PID:-} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$root/webapp/backend" && ./.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8766 --reload --reload-dir app --log-level info) &
BACK_PID=$!

(cd "$root/webapp/frontend" && npm run dev) &
FRONT_PID=$!

echo ""
echo "Started:"
echo "  backend  http://127.0.0.1:8766  (pid $BACK_PID)"
echo "  frontend http://localhost:5173  (pid $FRONT_PID)"
echo "Ctrl-C to stop both."
wait
