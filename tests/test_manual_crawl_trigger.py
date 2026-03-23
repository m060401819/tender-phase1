from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
import app.services.source_crawl_trigger_service as trigger_module
from app.api.endpoints.sources import (
    get_crawl_command_runner,
    get_crawl_job_dispatcher,
    get_source_crawl_trigger_service,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite
from app.repositories import SourceSiteRepository
from app.services import (
    CrawlJobService,
    PendingCrawlJobDispatchService,
    SourceCrawlTriggerService,
    SubprocessCrawlJobDispatcher,
)
from app.services.source_crawl_trigger_service import _database_url_for_bind


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


class FailingQueueTriggerService:
    def __init__(self, *, session: Session) -> None:
        self.session = session

    def queue_manual_crawl(self, **_: object) -> None:
        raise RuntimeError("mock enqueue failed")


class DummyProcess:
    def wait(self, timeout: int | None = None) -> int:  # pragma: no cover - defensive stub
        _ = timeout
        return 0


def _next_id(session: Session, model_cls: type) -> int:
    return int(session.scalar(select(func.max(model_cls.id))) or 0) + 1


def _seed_source(session_factory: sessionmaker, *, is_active: bool) -> None:
    with session_factory() as session:
        session.add(
            SourceSite(
                id=_next_id(session, SourceSite),
                code="anhui_ggzy_zfcg",
                name="安徽省公共资源交易监管网（政府采购）",
                base_url="https://ggzy.ah.gov.cn/",
                description="manual crawl trigger test",
                is_active=is_active,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=7,
                schedule_enabled=False,
                schedule_days=1,
            )
        )
        session.commit()


def _build_client(
    tmp_path: Path,
    *,
    runner: StubRunner,
    is_active: bool,
    dispatcher: object | None = None,
) -> tuple[TestClient, sessionmaker, object, str]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'manual_crawl_trigger.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_source(session_factory, is_active=is_active)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_crawl_command_runner] = lambda: runner
    if dispatcher is not None:
        app.dependency_overrides[get_crawl_job_dispatcher] = lambda: dispatcher

    client = TestClient(app)
    return client, session_factory, engine, db_url


def test_manual_crawl_route_creates_pending_manual_job_and_redirects(tmp_path: Path, admin_csrf) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, _ = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers.get("location") == "/admin/crawl-jobs?source_code=anhui_ggzy_zfcg&created_job_id=1"

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            created = jobs[0]
            assert created.source_site_id == source.id
            assert created.job_type == "manual"
            assert created.status == "pending"
            assert created.triggered_by == "admin_ui"
            assert created.retry_of_job_id is None
            assert created.picked_at is None
            assert created.started_at is None
            assert created.timeout_at is None

        assert runner.commands == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_source_sites_page_contains_manual_crawl_button(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, _, engine, _ = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.get("/admin/source-sites")
        assert response.status_code == 200
        assert "手动抓取" in response.text
        assert 'name="csrf_token"' in response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' in response.text
        assert 'name="return_to" value="source-sites"' in response.text
        assert 'href="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' not in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_is_post_only(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, _, engine, _ = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.get("/admin/sources/anhui_ggzy_zfcg/manual-crawl")
        assert response.status_code == 405
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_rejects_inactive_source_with_page_message(tmp_path: Path, admin_csrf) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, _ = _build_client(tmp_path, runner=runner, is_active=False)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client, data={"return_to": "source-sites"}),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "来源未启用，无法手动抓取" in response.text
        assert "来源网站列表" in response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob)).all()
            assert jobs == []

        assert runner.commands == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_shows_enqueue_failure_message_on_source_sites_page(tmp_path: Path, admin_csrf) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, _ = _build_client(tmp_path, runner=runner, is_active=True)
    failing_session = session_factory()
    app.dependency_overrides[get_source_crawl_trigger_service] = (
        lambda: FailingQueueTriggerService(session=failing_session)
    )
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client, data={"return_to": "source-sites"}),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "手动抓取任务创建失败：mock enqueue failed" in response.text
        assert "来源网站列表" in response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob)).all()
            assert jobs == []

        assert runner.commands == []
    finally:
        failing_session.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_rejects_when_same_source_already_has_active_job(tmp_path: Path, admin_csrf) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, _ = _build_client(tmp_path, runner=runner, is_active=True)
    service = CrawlJobService(session_factory=session_factory)
    try:
        active_job = service.create_job(
            source_code="anhui_ggzy_zfcg",
            job_type="manual",
            triggered_by="pytest-active",
        )

        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client, data={"return_to": "source-sites"}),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "已有进行中的抓取任务" in response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].id == active_job.id
            assert jobs[0].status == "pending"

        assert runner.commands == []
    finally:
        service.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_rejects_second_submit_while_first_job_still_pending(tmp_path: Path, admin_csrf) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, _ = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        first = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client, data={"return_to": "source-sites"}),
            follow_redirects=False,
        )
        assert first.status_code == 303

        second = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client, data={"return_to": "source-sites"}),
            follow_redirects=True,
        )
        assert second.status_code == 200
        assert "已有进行中的抓取任务" in second.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].status == "pending"
            assert jobs[0].triggered_by == "admin_ui"

        assert runner.commands == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_database_url_for_bind_keeps_database_password() -> None:
    class DummyBind:
        url = make_url("postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1")

    assert _database_url_for_bind(DummyBind()) == "postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1"


def test_pending_manual_job_can_be_consumed_after_request_process_returns(tmp_path: Path, admin_csrf) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, db_url = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client),
            follow_redirects=False,
        )
        assert response.status_code == 303
    finally:
        client.close()
        app.dependency_overrides.clear()

    dispatch_service = PendingCrawlJobDispatchService.from_database_url(
        db_url,
        job_dispatcher=InlineDispatcher(session_factory=session_factory, runner=runner),
        project_root=tmp_path,
    )
    try:
        sweep_result = dispatch_service.dispatch_pending_jobs()
        assert sweep_result.scanned_count == 1
        assert sweep_result.handoff_count == 1
        assert runner.commands

        with session_factory() as session:
            job = session.get(CrawlJob, 1)
            assert job is not None
            assert job.status == "succeeded"
            assert job.picked_at is not None
            assert job.started_at is not None
    finally:
        dispatch_service.close()
        engine.dispose()


def test_pending_dispatcher_retries_then_marks_job_as_dispatched_for_admin_feedback(
    tmp_path: Path,
    admin_csrf,
    monkeypatch,
    caplog,
) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, db_url = _build_client(tmp_path, runner=runner, is_active=True)
    dispatcher = SubprocessCrawlJobDispatcher(max_dispatch_attempts=2, retry_delay_seconds=0)
    attempts = {"count": 0}

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("spawn once")
        return DummyProcess()

    monkeypatch.setattr(trigger_module.subprocess, "Popen", fake_popen)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client),
            follow_redirects=False,
        )
        assert response.status_code == 303

        dispatch_service = PendingCrawlJobDispatchService.from_database_url(
            db_url,
            job_dispatcher=dispatcher,
            project_root=tmp_path,
        )
        try:
            with caplog.at_level(logging.INFO):
                dispatch_service.dispatch_pending_jobs()
        finally:
            dispatch_service.close()

        assert any(getattr(record, "event", "") == "crawl_job_dispatch_retry" for record in caplog.records)
        assert any(getattr(record, "event", "") == "crawl_job_dispatched" for record in caplog.records)

        with session_factory() as session:
            job = session.get(CrawlJob, 1)
            assert job is not None
            assert job.status == "pending"
            assert job.picked_at is not None
            assert job.started_at is None
            assert job.timeout_at is not None

        detail = client.get("/admin/crawl-jobs/1")
        assert detail.status_code == 200
        assert "等待 Worker 启动" in detail.text
        assert 'data-live-refresh="true"' in detail.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_pending_dispatcher_abandons_failed_handoff_and_marks_job_failed(
    tmp_path: Path,
    admin_csrf,
    monkeypatch,
    caplog,
) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine, db_url = _build_client(tmp_path, runner=runner, is_active=True)
    dispatcher = SubprocessCrawlJobDispatcher(max_dispatch_attempts=2, retry_delay_seconds=0)

    def always_fail_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        raise OSError("spawn boom")

    monkeypatch.setattr(trigger_module.subprocess, "Popen", always_fail_popen)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data=admin_csrf(client),
            follow_redirects=False,
        )
        assert response.status_code == 303

        dispatch_service = PendingCrawlJobDispatchService.from_database_url(
            db_url,
            job_dispatcher=dispatcher,
            project_root=tmp_path,
        )
        try:
            with caplog.at_level(logging.WARNING):
                dispatch_service.dispatch_pending_jobs()
        finally:
            dispatch_service.close()

        assert any(getattr(record, "event", "") == "crawl_job_dispatch_retry" for record in caplog.records)
        assert any(getattr(record, "event", "") == "crawl_job_dispatch_abandoned" for record in caplog.records)

        with session_factory() as session:
            job = session.get(CrawlJob, 1)
            assert job is not None
            assert job.status == "failed"
            assert job.failure_reason == "后台任务派发失败：spawn boom"
            assert job.runtime_stats_json is not None
            assert job.runtime_stats_json["run_stage"] == "dispatch_abandoned"
            assert "任务派发失败" in (job.message or "")

        detail = client.get("/admin/crawl-jobs/1")
        assert detail.status_code == 200
        assert "失败" in detail.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
