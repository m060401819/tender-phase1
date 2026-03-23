from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.core.auth as auth_module
from app.core.config import Settings


def _clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("APP_ENV", "DATABASE_URL", "AUTH_BASIC_USERS_JSON", "ADMIN_AUTH_SECRET", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)


def test_settings_keep_dev_defaults_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.app_env == "dev"
    assert settings.database_url == Settings.DEVELOPMENT_DATABASE_URL
    assert settings.log_level == "INFO"
    assert settings.is_production is False


def test_settings_reject_invalid_auth_basic_users_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(auth_basic_users_json='{"username":"admin"}', _env_file=None)

    assert "AUTH_BASIC_USERS_JSON must be a JSON array" in str(exc_info.value)


def test_settings_require_explicit_runtime_values_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(app_env="prod", _env_file=None)

    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "ADMIN_AUTH_SECRET" in message
    assert "LOG_LEVEL" in message


def test_settings_reject_default_dev_database_url_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            database_url=Settings.DEVELOPMENT_DATABASE_URL,
            admin_auth_secret="prod-secret",
            log_level="info",
            _env_file=None,
        )

    assert "默认开发 DATABASE_URL" in str(exc_info.value)


def test_settings_accept_explicit_runtime_values_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_runtime_env(monkeypatch)

    settings = Settings(
        app_env="prod",
        database_url="postgresql+psycopg://tender:secret@db.internal:5432/tender_phase1",
        admin_auth_secret="prod-secret",
        log_level="warn",
        _env_file=None,
    )

    assert settings.is_production is True
    assert settings.log_level == "WARNING"
    assert settings.log_level_value > 0


def test_admin_auth_secret_signs_admin_csrf_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    issued_at = int(time.time())
    nonce = "stable-test-nonce"

    monkeypatch.setattr(auth_module.settings, "admin_auth_secret", "secret-one")
    token = auth_module.build_admin_csrf_token(username="admin-user", issued_at=issued_at, nonce=nonce)

    assert auth_module._is_valid_admin_csrf_token(token=token, username="admin-user") is True

    monkeypatch.setattr(auth_module.settings, "admin_auth_secret", "secret-two")

    assert auth_module._is_valid_admin_csrf_token(token=token, username="admin-user") is False


def test_app_import_refuses_incomplete_production_runtime(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["APP_ENV"] = "prod"
    env["PYTHONPATH"] = (
        f"{project_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(project_root)
    )
    for key in ("DATABASE_URL", "AUTH_BASIC_USERS_JSON", "ADMIN_AUTH_SECRET", "LOG_LEVEL"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined_output = f"{result.stdout}\n{result.stderr}"
    assert "DATABASE_URL" in combined_output
    assert "ADMIN_AUTH_SECRET" in combined_output
    assert "LOG_LEVEL" in combined_output


def test_compose_profiles_separate_dev_defaults_and_prod_template() -> None:
    dev_compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    prod_compose = Path("docker-compose.prod.example.yml").read_text(encoding="utf-8")

    assert "Development-only compose profile" in dev_compose
    assert "APP_ENV: dev" in dev_compose
    assert "AUTH_BASIC_USERS_JSON:" in dev_compose
    assert "viewer_user" in dev_compose
    assert "admin_user" in dev_compose
    assert "LOG_LEVEL: INFO" in dev_compose

    assert "DATABASE_URL: ${DATABASE_URL:?DATABASE_URL is required}" in prod_compose
    assert "APP_ENV: ${APP_ENV:?APP_ENV is required}" in prod_compose
    assert "AUTH_BASIC_USERS_JSON: ${AUTH_BASIC_USERS_JSON:?AUTH_BASIC_USERS_JSON is required}" in prod_compose
    assert "ADMIN_AUTH_SECRET: ${ADMIN_AUTH_SECRET:?ADMIN_AUTH_SECRET is required}" in prod_compose
    assert "LOG_LEVEL: ${LOG_LEVEL:?LOG_LEVEL is required}" in prod_compose
    assert "./:/app" not in prod_compose
    assert "POSTGRES_PASSWORD: postgres" not in prod_compose


def test_env_example_includes_local_basic_auth_users() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "AUTH_BASIC_USERS_JSON=" in env_example
    assert "viewer_user" in env_example
    assert "ops_user" in env_example
    assert "admin_user" in env_example
