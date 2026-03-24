from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_project_python_executable(*, project_root: Path | None = None) -> str:
    root = project_root or Path(__file__).resolve().parents[2]

    for candidate in _iter_python_candidates(project_root=root):
        normalized = _normalize_existing_python_path(candidate)
        if normalized is not None:
            return normalized

    current = Path(sys.executable).expanduser()
    if not current.is_absolute():
        current = current.absolute()
    return str(current)


def _iter_python_candidates(*, project_root: Path) -> list[Path]:
    candidates = _venv_python_candidates(project_root / ".venv")

    virtual_env = os.environ.get("VIRTUAL_ENV", "").strip()
    if virtual_env:
        candidates.extend(_venv_python_candidates(Path(virtual_env)))

    candidates.append(Path(sys.executable))
    return candidates


def _venv_python_candidates(venv_root: Path) -> list[Path]:
    return [
        venv_root / "bin" / "python",
        venv_root / "Scripts" / "python.exe",
    ]


def _normalize_existing_python_path(candidate: Path) -> str | None:
    path = candidate.expanduser()
    if not path.is_absolute():
        path = path.absolute()
    if not path.exists():
        return None
    return str(path)
