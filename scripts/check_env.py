#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class DependencyCheck:
    kind: str
    name: str
    purpose: str


RUNTIME_PROFILE = (
    DependencyCheck("module", "fastapi", "FastAPI API and admin runtime"),
    DependencyCheck("module", "sqlalchemy", "database access layer"),
    DependencyCheck("module", "psycopg", "PostgreSQL driver"),
    DependencyCheck("module", "alembic", "database migrations"),
)

CRAWL_PROFILE = (
    DependencyCheck("module", "scrapy", "multi-source crawling runtime"),
    DependencyCheck("module", "playwright", "JS-rendered source support"),
)

TEST_PROFILE = (
    DependencyCheck("module", "pytest", "test runner"),
    DependencyCheck("module", "httpx", "FastAPI TestClient transport dependency"),
)

PROFILE_CHECKS = {
    "runtime": RUNTIME_PROFILE,
    "crawl": CRAWL_PROFILE,
    "test": TEST_PROFILE,
    "dev": (*RUNTIME_PROFILE, *CRAWL_PROFILE, *TEST_PROFILE),
}

INSTALL_HINTS = {
    "runtime": "python3 -m pip install --upgrade pip setuptools wheel && python3 -m pip install -e .",
    "crawl": "python3 -m pip install --upgrade pip setuptools wheel && python3 -m pip install -e .",
    "test": "python3 -m pip install --upgrade pip setuptools wheel && python3 -m pip install -e .[test]",
    "dev": "python3 -m pip install --upgrade pip setuptools wheel && python3 -m pip install -e .[dev]",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether the current Python environment contains the dependencies required by a profile."
    )
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_CHECKS.keys()),
        default="dev",
        help="Dependency profile to validate.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--extra-module",
        action="append",
        default=[],
        help="Extra import name to validate in addition to the built-in profile checks.",
    )
    return parser.parse_args()


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _build_checks(args: argparse.Namespace) -> tuple[DependencyCheck, ...]:
    extra_checks = tuple(
        DependencyCheck("module", module_name, "extra CLI dependency check")
        for module_name in args.extra_module
    )
    return (*PROFILE_CHECKS[args.profile], *extra_checks)


def _collect_results(profile: str, checks: tuple[DependencyCheck, ...]) -> dict[str, object]:
    results: list[dict[str, object]] = []
    missing = 0

    for check in checks:
        available = _module_available(check.name)
        if not available:
            missing += 1

        result = asdict(check)
        result["ok"] = available
        results.append(result)

    return {
        "profile": profile,
        "ok": missing == 0,
        "missing_count": missing,
        "install_hint": INSTALL_HINTS[profile],
        "checks": results,
    }


def _render_text(payload: dict[str, object]) -> str:
    lines = [f"Dependency profile: {payload['profile']}"]
    for check in payload["checks"]:
        status = "OK" if check["ok"] else "MISSING"
        lines.append(f"[{status}] {check['kind']} {check['name']} - {check['purpose']}")

    if payload["ok"]:
        lines.append("Result: environment is ready.")
    else:
        lines.append(
            "Result: environment is incomplete. Install with: "
            f"{payload['install_hint']}"
        )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    checks = _build_checks(args)
    payload = _collect_results(args.profile, checks)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(payload))

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
