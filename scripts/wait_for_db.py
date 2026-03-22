#!/usr/bin/env python3
from __future__ import annotations

import os
import time

from sqlalchemy import create_engine, text


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")

    max_attempts = int(os.getenv("DB_WAIT_MAX_ATTEMPTS", "60"))
    interval = float(os.getenv("DB_WAIT_INTERVAL_SECONDS", "2"))

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            print(f"[entrypoint] postgres ready after {attempt} attempt(s)")
            return 0
        except Exception as exc:  # pragma: no cover
            last_error = exc
            print(f"[entrypoint] waiting postgres ({attempt}/{max_attempts}): {exc}")
            time.sleep(interval)

    raise SystemExit(f"postgres not ready: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
