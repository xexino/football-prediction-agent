#!/usr/bin/env bash
# Consistent online backup of the SQLite database to data/backups/fil-<timestamp>.db.gz (keeps 14).
set -euo pipefail
cd "$(dirname "$0")/../backend" && python3 -m fil backup
