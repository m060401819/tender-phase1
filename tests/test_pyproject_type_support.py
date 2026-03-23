from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any


PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"
EXPECTED_APSCHEDULER_MODULES = {
    "apscheduler.jobstores.base",
    "apscheduler.schedulers.background",
    "apscheduler.triggers.interval",
}


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def test_dev_extra_includes_types_openpyxl() -> None:
    pyproject = _load_pyproject()
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(dependency.startswith("types-openpyxl==") for dependency in dev_dependencies)


def test_mypy_apscheduler_override_is_local_and_explicit() -> None:
    pyproject = _load_pyproject()
    mypy_config = pyproject["tool"]["mypy"]
    overrides = mypy_config["overrides"]

    assert "ignore_missing_imports" not in mypy_config
    assert any(
        set(override["module"]) == EXPECTED_APSCHEDULER_MODULES and override.get("ignore_missing_imports") is True
        for override in overrides
    )
