from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.endpoints.sources import get_crawl_command_runner
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite


class StubRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, cwd: Path) -> int:
        self.commands.append(command)
        return self.return_code



def _next_id(session: Session, model_cls: type) -> int:
    return int(session.scalar(select(func.max(model_cls.id))) or 0) + 1



def _seed_source(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        session.add(
            SourceSite(
                id=_next_id(session, SourceSite),
                code="anhui_ggzy_zfcg",
                name="安徽省公共资源交易监管网（政府采购）",
                base_url="https://ggzy.ah.gov.cn/",
                description="admin test source",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
            )
        )
        session.commit()



def _build_client(tmp_path: Path, *, runner: StubRunner) -> tuple[TestClient, sessionmaker, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'source_admin_pages.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_source(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_crawl_command_runner] = lambda: runner

    client = TestClient(app)
    return client, session_factory, engine



def test_admin_sources_list_and_detail_pages(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, _, engine = _build_client(tmp_path, runner=runner)
    try:
        list_response = client.get("/admin/sources")
        assert list_response.status_code == 200
        assert "来源管理" in list_response.text
        assert "anhui_ggzy_zfcg" in list_response.text
        assert "/admin/sources/anhui_ggzy_zfcg" in list_response.text

        detail_response = client.get("/admin/sources/anhui_ggzy_zfcg")
        assert detail_response.status_code == 200
        assert "来源详情 anhui_ggzy_zfcg" in detail_response.text
        assert "编辑来源配置" in detail_response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/config"' in detail_response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/crawl-jobs"' in detail_response.text

        not_found = client.get("/admin/sources/not-found")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_source_detail_can_update_source_config(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/config",
            data={
                "is_active": "false",
                "supports_js_render": "true",
                "crawl_interval_minutes": "25",
                "default_max_pages": "6",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/admin/sources/anhui_ggzy_zfcg"

        detail_response = client.get("/admin/sources/anhui_ggzy_zfcg")
        assert detail_response.status_code == 200
        assert "False" in detail_response.text
        assert "True" in detail_response.text
        assert "25" in detail_response.text
        assert "6" in detail_response.text

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.is_active is False
            assert source.supports_js_render is True
            assert source.crawl_interval_minutes == 25
            assert source.default_max_pages == 6

        bad_request = client.post(
            "/admin/sources/anhui_ggzy_zfcg/config",
            data={
                "is_active": "invalid",
                "supports_js_render": "true",
                "crawl_interval_minutes": "25",
                "default_max_pages": "6",
            },
            follow_redirects=False,
        )
        assert bad_request.status_code == 400

        not_found = client.post(
            "/admin/sources/not-found/config",
            data={
                "is_active": "true",
                "supports_js_render": "false",
                "crawl_interval_minutes": "60",
                "default_max_pages": "1",
            },
            follow_redirects=False,
        )
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_admin_source_detail_can_trigger_manual_crawl_job(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data={"max_pages": "2"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers.get("location")
        assert location is not None
        assert location.startswith("/admin/crawl-jobs/")

        assert len(runner.commands) == 1
        assert "max_pages=2" in " ".join(runner.commands[0])

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.desc())).all()
            assert len(jobs) == 1
            assert jobs[0].job_type == "manual"
            assert jobs[0].status == "succeeded"
            assert jobs[0].triggered_by == "admin"

        bad_request = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data={"max_pages": "0"},
            follow_redirects=False,
        )
        assert bad_request.status_code == 400

        not_found = client.post(
            "/admin/sources/not-found/crawl-jobs",
            data={"max_pages": "1"},
            follow_redirects=False,
        )
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
