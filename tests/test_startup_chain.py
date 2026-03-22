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


def test_dev_up_script_restarts_project_processes_by_default() -> None:
    script = Path("scripts/dev_up.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert 'DEV_UP_REUSE_RUNNING="${DEV_UP_REUSE_RUNNING:-0}"' in content
    assert "默认重启以加载最新代码" in content
    assert "按 DEV_UP_REUSE_RUNNING=1 复用现有进程" in content


def test_app_entrypoint_only_waits_and_starts_uvicorn() -> None:
    script = Path("scripts/app_entrypoint.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert "python scripts/wait_for_db.py" in content
    assert "alembic upgrade head" not in content
    assert "python scripts/seed_sources.py --demo" not in content
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in content


def test_migrate_entrypoint_waits_and_runs_alembic() -> None:
    script = Path("scripts/migrate_entrypoint.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert "python scripts/wait_for_db.py" in content
    assert "alembic upgrade head" in content
    assert "seed_sources.py --demo" not in content


def test_seed_demo_entrypoint_waits_and_runs_demo_seed() -> None:
    script = Path("scripts/seed_demo_entrypoint.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")

    assert "python scripts/wait_for_db.py" in content
    assert "python scripts/seed_sources.py --demo" in content
