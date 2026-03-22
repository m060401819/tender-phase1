from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_self_check(*args: str) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, str(project_root / "scripts" / "check_env.py"), *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_test_profile_self_check_reports_testclient_dependencies() -> None:
    result = _run_self_check("--profile", "test", "--format", "json")

    assert result.returncode == 0, result.stdout or result.stderr
    payload = json.loads(result.stdout)

    assert payload["profile"] == "test"
    assert payload["ok"] is True
    assert payload["install_hint"] == (
        "python3 -m pip install --upgrade pip setuptools wheel && "
        "python3 -m pip install -e .[test]"
    )

    dependency_names = {item["name"] for item in payload["checks"]}
    assert {"pytest", "httpx"} <= dependency_names


def test_dev_profile_self_check_covers_runtime_crawl_and_test_dependencies() -> None:
    result = _run_self_check("--profile", "dev", "--format", "json")

    assert result.returncode == 0, result.stdout or result.stderr
    payload = json.loads(result.stdout)

    dependency_names = {item["name"] for item in payload["checks"]}
    assert {
        "fastapi",
        "sqlalchemy",
        "psycopg",
        "alembic",
        "scrapy",
        "playwright",
        "pytest",
        "httpx",
    } <= dependency_names


def test_self_check_returns_non_zero_when_extra_dependency_is_missing() -> None:
    missing_module = "module_that_should_not_exist_for_env_check"
    result = _run_self_check(
        "--profile",
        "test",
        "--format",
        "json",
        "--extra-module",
        missing_module,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)

    assert payload["ok"] is False
    assert payload["missing_count"] >= 1
    missing_checks = {item["name"] for item in payload["checks"] if not item["ok"]}
    assert missing_module in missing_checks
