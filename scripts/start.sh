#!/usr/bin/env bash
# Start the Football Intelligence Lab (API + dashboard + scheduler) in the background.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
if [ ! -d backend/fil/static ]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi
if pgrep -f "python3 -m fil serve" >/dev/null; then echo "already running"; exit 0; fi
cd backend
nohup python3 -m fil serve >> ../data/logs/server.log 2>&1 &
echo "started (pid $!) — dashboard on http://localhost:${FIL_PORT:-8000}"
