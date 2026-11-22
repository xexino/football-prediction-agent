#!/usr/bin/env bash
# Usage: scripts/restore.sh data/backups/fil-YYYYMMDDTHHMMSSZ.db.gz   (stops the server first)
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: $0 <backup.db.gz>"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/stop.sh" || true
cd "$ROOT/backend" && python3 -m fil restore "$(realpath "$1")"
echo "restored; start again with scripts/start.sh"
