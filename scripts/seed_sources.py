#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ALLOWED_DEMO_SEED_ENVS = ("demo", "dev", "local", "test")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed source_site records for demo environment")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="seed demo source set (anhui + ggzy_gov_cn_deal + phase3 placeholder sources)",
    )
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL")
    return parser.parse_args()


def validate_demo_seed_environment(app_env: str | None = None) -> tuple[bool, str]:
    resolved_env = (app_env if app_env is not None else os.getenv("APP_ENV") or "").strip().lower()
    if resolved_env in ALLOWED_DEMO_SEED_ENVS:
        return True, resolved_env

    current_env = resolved_env or "unset"
    allowed_envs = ", ".join(ALLOWED_DEMO_SEED_ENVS)
    message = (
        "[seed-sources] refusing to seed demo sources because APP_ENV must be explicitly set "
        f"to one of: {allowed_envs}. current={current_env}"
    )
    return False, message


def main() -> int:
    args = parse_args()
    if not args.demo:
        print("[seed-sources] no seed profile selected, use --demo", file=sys.stderr)
        return 1

    allowed, detail = validate_demo_seed_environment()
    if not allowed:
        print(detail, file=sys.stderr)
        return 3

    from app.core.config import settings as app_settings  # noqa: E402
    from app.services import bootstrap_demo_sources  # noqa: E402

    database_url = (args.database_url or "").strip() or app_settings.database_url
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            try:
                sources = bootstrap_demo_sources(session)
            except SQLAlchemyError as exc:
                print(
                    "[seed-sources] failed to seed sources. "
                    "Please run `alembic upgrade head` first.",
                    file=sys.stderr,
                )
                print(f"[seed-sources] detail: {exc}", file=sys.stderr)
                return 2
            print(f"[seed-sources] seeded_or_updated={len(sources)}")
            for source in sources:
                print(
                    "[seed-sources] "
                    f"code={source.code} active={source.is_active} "
                    f"schedule_enabled={source.schedule_enabled} schedule_days={source.schedule_days} "
                    f"default_max_pages={source.default_max_pages}"
                )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
