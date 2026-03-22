from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'health_rule_admin.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, engine


def test_admin_health_rules_page_show_and_update(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        page = client.get("/admin/settings/health-rules")
        assert page.status_code == 200
        assert "健康度规则配置" in page.text
        assert "recent_error_warning_threshold" in page.text

        update = client.post(
            "/admin/settings/health-rules",
            data={
                "recent_error_warning_threshold": "2",
                "recent_error_critical_threshold": "5",
                "consecutive_failure_warning_threshold": "1",
                "consecutive_failure_critical_threshold": "2",
                "partial_warning_enabled": "false",
            },
            follow_redirects=False,
        )
        assert update.status_code == 303
        assert update.headers.get("location") == "/admin/settings/health-rules?updated=1"

        updated_page = client.get("/admin/settings/health-rules?updated=1")
        assert updated_page.status_code == 200
        assert "配置已更新" in updated_page.text
        assert 'value="2"' in updated_page.text
        assert 'value="5"' in updated_page.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_health_rules_page_reject_invalid_values(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        invalid = client.post(
            "/admin/settings/health-rules",
            data={
                "recent_error_warning_threshold": "9",
                "recent_error_critical_threshold": "5",
                "consecutive_failure_warning_threshold": "1",
                "consecutive_failure_critical_threshold": "1",
                "partial_warning_enabled": "true",
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 400
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
