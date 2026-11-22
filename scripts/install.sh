#!/usr/bin/env bash
# Install dependencies and build the dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r backend/requirements.txt
(cd frontend && npm ci --no-audit --no-fund && npm run build)
[ -f .env ] || cp .env.example .env
echo "installed. next: scripts/start.sh"
