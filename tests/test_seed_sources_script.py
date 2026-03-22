from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def _run_seed_sources(*args: str, env_overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    return subprocess.run(
        [sys.executable, "scripts/seed_sources.py", *args],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_seed_sources_rejects_demo_seed_without_explicit_app_env() -> None:
    result = _run_seed_sources("--demo", env_overrides={"APP_ENV": None})

    assert result.returncode == 3
    assert "APP_ENV must be explicitly set" in result.stderr
    assert "current=unset" in result.stderr


def test_seed_sources_rejects_demo_seed_in_prod_env() -> None:
    result = _run_seed_sources("--demo", env_overrides={"APP_ENV": "prod"})

    assert result.returncode == 3
    assert "APP_ENV must be explicitly set" in result.stderr
    assert "current=prod" in result.stderr


def test_seed_sources_allows_demo_seed_in_dev_env_before_db_seed_step(tmp_path: Path) -> None:
    result = _run_seed_sources(
        "--demo",
        "--database-url",
        f"sqlite+pysqlite:///{tmp_path / 'seed_sources_guard.db'}",
        env_overrides={"APP_ENV": "dev"},
    )

    assert result.returncode == 2
    assert "APP_ENV must be explicitly set" not in result.stderr
    assert "Please run `alembic upgrade head` first." in result.stderr
