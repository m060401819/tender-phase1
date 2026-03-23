#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
APP_HOST="${APP_HOST:-127.0.0.1}"

python scripts/wait_for_db.py

echo "[entrypoint] starting uvicorn"
exec uvicorn app.main:app --host "$APP_HOST" --port 8000
