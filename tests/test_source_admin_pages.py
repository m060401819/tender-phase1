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
                schedule_enabled=False,
                schedule_days=1,
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
        assert "/admin/sources/new" in list_response.text

        detail_response = client.get("/admin/sources/anhui_ggzy_zfcg")
        assert detail_response.status_code == 200
        assert "来源详情 anhui_ggzy_zfcg" in detail_response.text
        assert "运行健康摘要" in detail_response.text
        assert "today_crawl_job_count" in detail_response.text
        assert "last_retry_status" in detail_response.text
        assert "/reports/source-ops.xlsx?recent_hours=24&source_code=anhui_ggzy_zfcg" in detail_response.text
        assert "立即手动抓取" in detail_response.text
        assert "/admin/crawl-jobs?source_code=anhui_ggzy_zfcg" in detail_response.text
        assert "ops_filter=abnormal" in detail_response.text
        assert "/admin/source-sites" in detail_response.text
        assert "编辑来源配置" in detail_response.text
        assert "自动抓取配置" in detail_response.text
        assert "按年份回填" in detail_response.text
        assert 'name="backfill_year"' in detail_response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' in detail_response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/schedule"' in detail_response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/config"' in detail_response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/crawl-jobs"' in detail_response.text

        not_found = client.get("/admin/sources/not-found")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_source_sites_support_manual_create_entry_and_submit(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        list_page = client.get("/admin/source-sites")
        assert list_page.status_code == 200
        assert "新增来源网站" in list_page.text
        assert "/admin/sources/new" in list_page.text
        assert "招标信息工作台" in list_page.text
        assert "手动抓取" in list_page.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' in list_page.text
        assert 'href="https://ggzy.ah.gov.cn/' in list_page.text

        create_page = client.get("/admin/sources/new")
        assert create_page.status_code == 200
        assert "新增来源网站" in create_page.text
        assert 'name="source_code"' in create_page.text
        assert 'name="source_name"' in create_page.text
        assert 'name="official_url"' in create_page.text
        assert 'name="list_url"' in create_page.text
        assert 'name="schedule_days"' in create_page.text
        assert 'name="crawl_interval_minutes"' in create_page.text
        assert 'name="remark"' in create_page.text

        create_submit = client.post(
            "/admin/sources/new",
            data={
                "source_code": "new_power_source",
                "source_name": "新电力来源",
                "official_url": "https://example-power.com/",
                "list_url": "https://example-power.com/list",
                "remark": "phase3 manual create",
                "is_active": "true",
                "schedule_enabled": "true",
                "schedule_days": "2",
                "crawl_interval_minutes": "120",
                "default_max_pages": "8",
            },
            follow_redirects=False,
        )
        assert create_submit.status_code == 303
        assert create_submit.headers.get("location") == "/admin/source-sites?created=1&created_code=new_power_source"

        after = client.get("/admin/source-sites?created=1&created_code=new_power_source")
        assert after.status_code == 200
        assert "新增成功：new_power_source" in after.text
        assert "new_power_source" in after.text
        assert "新电力来源" in after.text

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "new_power_source"))
            assert source is not None
            assert source.name == "新电力来源"
            assert source.base_url == "https://example-power.com/"
            assert source.official_url == "https://example-power.com/"
            assert source.list_url == "https://example-power.com/list"
            assert source.description == "phase3 manual create"
            assert source.schedule_enabled is True
            assert source.schedule_days == 2
            assert source.crawl_interval_minutes == 120
            assert source.default_max_pages == 8

        invalid_submit = client.post(
            "/admin/sources/new",
            data={
                "source_code": "",
                "source_name": "",
                "official_url": "not-valid-url",
                "list_url": "",
                "remark": "",
                "is_active": "true",
                "schedule_enabled": "true",
                "schedule_days": "5",
                "crawl_interval_minutes": "0",
                "default_max_pages": "0",
            },
            follow_redirects=False,
        )
        assert invalid_submit.status_code == 400
        assert "提交失败" in invalid_submit.text
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
                "source_name": "Anhui Updated",
                "official_url": "https://ggzy.ah.gov.cn/",
                "list_url": "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
                "description": "updated note",
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
        assert "Anhui Updated" in detail_response.text
        assert "updated note" in detail_response.text

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.name == "Anhui Updated"
            assert source.official_url == "https://ggzy.ah.gov.cn/"
            assert source.list_url == "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1"
            assert source.description == "updated note"
            assert source.is_active is False
            assert source.supports_js_render is True
            assert source.crawl_interval_minutes == 25
            assert source.default_max_pages == 6

        bad_request = client.post(
            "/admin/sources/anhui_ggzy_zfcg/config",
            data={
                "source_name": "Anhui Updated",
                "official_url": "https://ggzy.ah.gov.cn/",
                "list_url": "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
                "description": "updated note",
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
                "source_name": "X",
                "official_url": "https://x.example.com/",
                "list_url": "https://x.example.com/list",
                "description": "x",
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



def test_admin_source_detail_can_update_schedule_config(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/schedule",
            data={
                "schedule_enabled": "true",
                "schedule_days": "3",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/admin/sources/anhui_ggzy_zfcg?schedule_updated=1"

        detail_response = client.get("/admin/sources/anhui_ggzy_zfcg?schedule_updated=1")
        assert detail_response.status_code == 200
        assert "配置已更新" in detail_response.text
        assert "3天一次" in detail_response.text
        assert "True" in detail_response.text

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.schedule_enabled is True
            assert source.schedule_days == 3
            assert source.next_scheduled_run_at is not None

        bad_request = client.post(
            "/admin/sources/anhui_ggzy_zfcg/schedule",
            data={
                "schedule_enabled": "true",
                "schedule_days": "5",
            },
            follow_redirects=False,
        )
        assert bad_request.status_code == 400

        not_found = client.post(
            "/admin/sources/not-found/schedule",
            data={
                "schedule_enabled": "true",
                "schedule_days": "1",
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


def test_admin_source_detail_can_trigger_backfill_crawl_job(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data={"job_type": "backfill", "backfill_year": "2026", "max_pages": "500"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers.get("location")
        assert location is not None
        assert location.startswith("/admin/crawl-jobs/")

        assert len(runner.commands) == 1
        command_text = " ".join(runner.commands[0])
        assert "backfill_year=2026" in command_text
        assert "max_pages=500" in command_text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.desc())).all()
            assert len(jobs) == 1
            assert jobs[0].job_type == "backfill"
            assert jobs[0].status == "succeeded"
            assert jobs[0].triggered_by == "admin"

        bad_year = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data={"job_type": "backfill", "backfill_year": "abc", "max_pages": "500"},
            follow_redirects=False,
        )
        assert bad_year.status_code == 400
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
