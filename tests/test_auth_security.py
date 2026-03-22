from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.endpoints.sources import get_crawl_command_runner, get_crawl_job_dispatcher
from app.core.auth import AuthenticatedUser, UserRole, get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite
from app.repositories import SourceSiteRepository
from app.services import SourceCrawlTriggerService


class StubRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.commands: list[list[str]] = []

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        heartbeat_callback=None,
        heartbeat_interval_seconds: int = 30,
    ) -> int:
        _ = (cwd, heartbeat_callback, heartbeat_interval_seconds)
        self.commands.append(command)
        return self.return_code


class InlineDispatcher:
    def __init__(self, *, session_factory: sessionmaker, runner: StubRunner) -> None:
        self.session_factory = session_factory
        self.runner = runner

    def dispatch(self, request, *, project_root: Path, database_url: str) -> None:  # type: ignore[no-untyped-def]
        _ = database_url
        with self.session_factory() as session:
            source = SourceSiteRepository(session).get_model_by_code(request.source_code)
            assert source is not None
            service = SourceCrawlTriggerService(
                session=session,
                command_runner=self.runner,
                project_root=project_root,
            )
            service.execute_crawl_job(
                source=source,
                crawl_job_id=request.crawl_job_id,
                job_type=request.job_type,
                max_pages=request.max_pages,
                backfill_year=request.backfill_year,
            )


def _next_id(session: Session, model_cls: type) -> int:
    return int(session.scalar(select(func.max(model_cls.id))) or 0) + 1


def _seed_source_and_failed_job(session_factory: sessionmaker) -> int:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        source = SourceSite(
            id=_next_id(session, SourceSite),
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="auth security test",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=5,
            schedule_enabled=False,
            schedule_days=1,
        )
        session.add(source)
        session.flush()
        failed_job = CrawlJob(
            id=_next_id(session, CrawlJob),
            source_site_id=int(source.id),
            job_type="manual",
            status="failed",
            triggered_by="pytest",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
            pages_fetched=1,
            documents_saved=1,
            notices_upserted=0,
            deduplicated_count=0,
            error_count=1,
            message="auth-test failed job",
        )
        session.add(failed_job)
        session.commit()
        return int(failed_job.id)


def _build_client(tmp_path: Path) -> tuple[TestClient, sessionmaker, StubRunner, int, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'auth_security.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    failed_job_id = _seed_source_and_failed_job(session_factory)
    runner = StubRunner(return_code=0)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_crawl_command_runner] = lambda: runner
    app.dependency_overrides[get_crawl_job_dispatcher] = (
        lambda: InlineDispatcher(session_factory=session_factory, runner=runner)
    )
    client = TestClient(app)
    return client, session_factory, runner, failed_job_id, engine


def _override_user(role: UserRole, *, username: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(username=username, role=role)


def test_public_source_query_api_remains_open_without_auth(tmp_path: Path) -> None:
    client, _, _, _, engine = _build_client(tmp_path)
    try:
        app.dependency_overrides.pop(get_current_user, None)
        response = client.get("/sources")
        assert response.status_code == 200
        assert response.json()[0]["code"] == "anhui_ggzy_zfcg"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_pages_require_authentication(tmp_path: Path) -> None:
    client, _, _, _, engine = _build_client(tmp_path)
    try:
        app.dependency_overrides.pop(get_current_user, None)

        dashboard = client.get("/admin/dashboard", follow_redirects=False)
        assert dashboard.status_code == 401
        assert "Basic" in dashboard.headers.get("www-authenticate", "")

        source_sites = client.get("/admin/source-sites", follow_redirects=False)
        assert source_sites.status_code == 401
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_viewer_cannot_trigger_crawl_or_retry_and_cannot_access_ops_page(tmp_path: Path) -> None:
    client, _, runner, failed_job_id, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.viewer, username="viewer-user")

        crawl_jobs_page = client.get("/admin/crawl-jobs")
        assert crawl_jobs_page.status_code == 200
        assert f'action="/admin/crawl-jobs/{failed_job_id}/retry"' not in crawl_jobs_page.text

        source_sites_page = client.get("/admin/source-sites")
        assert source_sites_page.status_code == 403

        manual_trigger = client.post("/admin/sources/anhui_ggzy_zfcg/manual-crawl", follow_redirects=False)
        assert manual_trigger.status_code == 403

        retry = client.post(f"/admin/crawl-jobs/{failed_job_id}/retry", follow_redirects=False)
        assert retry.status_code == 403
        assert runner.commands == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_ops_can_trigger_crawl_but_cannot_modify_source_config(tmp_path: Path) -> None:
    client, session_factory, runner, _, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.ops, username="ops-user")

        source_sites_page = client.get("/admin/source-sites")
        assert source_sites_page.status_code == 200
        assert 'href="/admin/sources/new"' not in source_sites_page.text
        assert 'href="/admin/sources/anhui_ggzy_zfcg"' not in source_sites_page.text

        trigger = client.post("/sources/anhui_ggzy_zfcg/crawl-jobs", json={"job_type": "manual"})
        assert trigger.status_code == 201
        assert len(runner.commands) == 1

        patch = client.patch("/sources/anhui_ggzy_zfcg", json={"name": "ops-updated"})
        assert patch.status_code == 403

        admin_detail = client.get("/admin/sources/anhui_ggzy_zfcg")
        assert admin_detail.status_code == 403

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.name == "安徽省公共资源交易监管网（政府采购）"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_can_modify_source_config(tmp_path: Path) -> None:
    client, session_factory, _, _, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.admin, username="admin-user")

        response = client.patch(
            "/sources/anhui_ggzy_zfcg",
            json={
                "name": "Anhui Updated",
                "official_url": "https://ggzy.ah.gov.cn/",
                "list_url": "https://ggzy.ah.gov.cn/zfcg/list",
                "description": "secured update",
                "is_active": True,
                "supports_js_render": False,
                "crawl_interval_minutes": 30,
                "default_max_pages": 8,
            },
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Anhui Updated"

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.name == "Anhui Updated"
            assert source.crawl_interval_minutes == 30
            assert source.default_max_pages == 8
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
