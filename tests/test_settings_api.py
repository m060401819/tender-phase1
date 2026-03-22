from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'settings_api.db'}"
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


def test_health_rule_settings_get_and_patch(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        current = client.get("/settings/health-rules")
        assert current.status_code == 200
        payload = current.json()
        assert payload["recent_error_warning_threshold"] == 3
        assert payload["recent_error_critical_threshold"] == 6
        assert payload["consecutive_failure_warning_threshold"] == 1
        assert payload["consecutive_failure_critical_threshold"] == 1
        assert payload["partial_warning_enabled"] is True

        updated = client.patch(
            "/settings/health-rules",
            json={
                "recent_error_warning_threshold": 2,
                "recent_error_critical_threshold": 4,
                "consecutive_failure_warning_threshold": 1,
                "consecutive_failure_critical_threshold": 2,
                "partial_warning_enabled": False,
            },
        )
        assert updated.status_code == 200
        updated_payload = updated.json()
        assert updated_payload["recent_error_warning_threshold"] == 2
        assert updated_payload["recent_error_critical_threshold"] == 4
        assert updated_payload["consecutive_failure_warning_threshold"] == 1
        assert updated_payload["consecutive_failure_critical_threshold"] == 2
        assert updated_payload["partial_warning_enabled"] is False
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_health_rule_settings_patch_rejects_invalid_config(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        invalid_order = client.patch(
            "/settings/health-rules",
            json={
                "recent_error_warning_threshold": 8,
                "recent_error_critical_threshold": 4,
            },
        )
        assert invalid_order.status_code == 400
        assert "cannot be greater" in invalid_order.json()["detail"]

        invalid_negative = client.patch(
            "/settings/health-rules",
            json={
                "consecutive_failure_warning_threshold": -1,
            },
        )
        assert invalid_negative.status_code == 400
        assert "must be >= 0" in invalid_negative.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_health_rule_update_applies_to_source_health_immediately(tmp_path: Path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'settings_api_apply.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        source = SourceSite(
            id=1,
            code="source_health_rule",
            name="source health rule",
            base_url="https://example.com",
            description="health rule apply test",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=1,
            schedule_enabled=False,
            schedule_days=1,
        )
        session.add(source)
        session.add(
            CrawlJob(
                id=11,
                source_site_id=1,
                job_type="manual",
                status="failed",
                triggered_by="test",
                pages_fetched=1,
                documents_saved=1,
                notices_upserted=0,
                deduplicated_count=0,
                error_count=1,
                message="failed once",
            )
        )
        session.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        before = client.get("/sources/source_health_rule/health")
        assert before.status_code == 200
        assert before.json()["health_status"] == "critical"

        patched = client.patch(
            "/settings/health-rules",
            json={
                "consecutive_failure_warning_threshold": 1,
                "consecutive_failure_critical_threshold": 2,
            },
        )
        assert patched.status_code == 200

        after = client.get("/sources/source_health_rule/health")
        assert after.status_code == 200
        assert after.json()["health_status"] == "warning"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
