from __future__ import annotations

from pathlib import Path


def test_dev_up_script_contains_one_click_startup_chain() -> None:
    script = Path("scripts/dev_up.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert "source \"$PROJECT_ROOT/.venv/bin/activate\"" in content
    assert "docker compose up -d postgres" in content
    assert "alembic upgrade head" in content
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in content
    assert "dev_web.log" in content
    assert "http://127.0.0.1:8000/admin/home" in content
    assert "http://127.0.0.1:8000/docs" in content


def test_app_entrypoint_runs_wait_migrate_and_uvicorn() -> None:
    script = Path("scripts/app_entrypoint.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert "SELECT 1" in content
    assert "alembic upgrade head" in content
    assert "python scripts/seed_sources.py --demo" in content
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in content
