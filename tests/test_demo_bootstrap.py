from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import SourceSite
from app.services import bootstrap_demo_sources


def _build_session_factory(tmp_path: Path) -> tuple[sessionmaker, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'demo_bootstrap.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return session_factory, engine


def test_bootstrap_demo_sources_is_idempotent(tmp_path: Path) -> None:
    session_factory, engine = _build_session_factory(tmp_path)
    try:
        with session_factory() as session:
            first = bootstrap_demo_sources(session)
            second = bootstrap_demo_sources(session)

            assert len(first) >= 5
            assert len(second) >= 5
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.base_url.startswith("https://ggzy.ah.gov.cn/")
            assert source.official_url.startswith("https://ggzy.ah.gov.cn/")
            assert source.list_url.startswith("https://ggzy.ah.gov.cn/zfcg/list")
            assert source.is_active is True
            assert source.schedule_enabled is True
            assert source.default_max_pages == 50

            total = int(session.scalar(select(func.count(SourceSite.id))) or 0)
            assert total >= 5
    finally:
        engine.dispose()


def test_demo_bootstrap_smoke_for_admin_pages_and_api(tmp_path: Path) -> None:
    session_factory, engine = _build_session_factory(tmp_path)
    try:
        with session_factory() as session:
            bootstrap_demo_sources(session)

        def override_get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        health = client.get("/healthz")
        assert health.status_code == 200

        sources = client.get("/sources")
        assert sources.status_code == 200
        payload = sources.json()
        assert len(payload) >= 1
        assert payload[0]["code"] == "anhui_ggzy_zfcg"

        source_sites = client.get("/admin/source-sites")
        assert source_sites.status_code == 200
        assert "anhui_ggzy_zfcg" in source_sites.text
        assert "暂无来源记录" not in source_sites.text

        home = client.get("/admin/home")
        assert home.status_code == 200
        assert "系统总览 Dashboard" in home.text

        dashboard_stats = client.get("/stats/overview")
        assert dashboard_stats.status_code == 200
        assert dashboard_stats.json()["source_count"] >= 1

        report = client.get("/reports/source-ops.xlsx")
        assert report.status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
