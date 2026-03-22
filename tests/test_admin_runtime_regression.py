from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.endpoints import admin_dashboard
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite, TenderNotice


def _build_client(tmp_path: Path, db_name: str) -> tuple[TestClient, sessionmaker, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / db_name}"
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
    return client, session_factory, engine


def _seed_minimal_data(session_factory: sessionmaker) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        source = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="minimal regression source",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=1,
            schedule_enabled=False,
            schedule_days=1,
            created_at=now,
            updated_at=now,
        )
        session.add(source)

        session.add(
            CrawlJob(
                id=1,
                source_site_id=1,
                job_type="manual",
                status="succeeded",
                triggered_by="pytest",
                started_at=now,
                finished_at=now + timedelta(minutes=1),
                pages_fetched=1,
                documents_saved=1,
                notices_upserted=1,
                deduplicated_count=0,
                error_count=0,
                list_items_seen=1,
                list_items_unique=1,
                list_items_source_duplicates_skipped=0,
                detail_pages_fetched=1,
                records_inserted=1,
                records_updated=0,
                source_duplicates_suppressed=0,
                message="ok",
                created_at=now,
                updated_at=now,
            )
        )

        session.add(
            TenderNotice(
                id=1,
                source_site_id=1,
                external_id="AH-MIN-001",
                project_code="MIN-001",
                dedup_hash="dedup-min-001",
                source_duplicate_key="src-dup-min-001",
                title="最小数据测试公告",
                notice_type="announcement",
                issuer="合肥测试单位",
                region="合肥",
                published_at=now,
                deadline_at=now + timedelta(days=3),
                budget_amount=None,
                budget_currency="CNY",
                summary="minimal regression notice",
                first_published_at=now,
                latest_published_at=now,
                current_version_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_admin_core_pages_open_with_empty_data(tmp_path: Path) -> None:
    client, _, engine = _build_client(tmp_path, "admin_runtime_empty.db")
    try:
        for path in ("/admin/home", "/admin/source-sites", "/admin/notices"):
            response = client.get(path)
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_home_empty_data_shows_defaults(tmp_path: Path) -> None:
    client, _, engine = _build_client(tmp_path, "admin_runtime_empty_defaults.db")
    try:
        response = client.get("/admin/home")
        assert response.status_code == 200
        assert "系统总览 Dashboard" in response.text
        assert "今日暂无新增" in response.text
        assert "active=0" in response.text
        assert "running=0" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_core_pages_open_with_minimal_data(tmp_path: Path) -> None:
    client, session_factory, engine = _build_client(tmp_path, "admin_runtime_minimal.db")
    _seed_minimal_data(session_factory)
    try:
        home = client.get("/admin/home")
        assert home.status_code == 200
        assert "系统总览 Dashboard" in home.text
        assert "active=1" in home.text
        assert "统计数据暂不可用" not in home.text

        source_sites = client.get("/admin/source-sites")
        assert source_sites.status_code == 200
        assert "anhui_ggzy_zfcg" in source_sites.text

        notices = client.get("/admin/notices")
        assert notices.status_code == 200
        assert "最小数据测试公告" in notices.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_home_fallbacks_to_defaults_when_stats_query_fails(tmp_path: Path, monkeypatch) -> None:
    client, _, engine = _build_client(tmp_path, "admin_runtime_stats_failure.db")

    def _raise_sql_error(*_: object, **__: object):
        raise SQLAlchemyError("forced stats error")

    monkeypatch.setattr(admin_dashboard.StatsService, "get_overview", _raise_sql_error)

    try:
        response = client.get("/admin/home")
        assert response.status_code == 200
        assert "统计数据暂不可用，已降级为默认值" in response.text
        assert "active=0" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
