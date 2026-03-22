#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

python scripts/wait_for_db.py

echo "[migrate] running alembic upgrade head"
exec alembic upgrade head
