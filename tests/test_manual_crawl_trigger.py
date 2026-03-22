from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, Thread

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.api.endpoints.admin_sources as admin_sources_module
import app.models  # noqa: F401
from app.api.endpoints.admin_sources import _run_manual_crawl_job_background
from app.api.endpoints.sources import get_crawl_command_runner, get_source_crawl_trigger_service
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite
from app.services import CrawlJobService
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


class BlockingRunner(StubRunner):
    def __init__(self, *, release_event: Event, return_code: int = 0) -> None:
        super().__init__(return_code=return_code)
        self.release_event = release_event
        self.started_event = Event()

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
        self.started_event.set()
        released = self.release_event.wait(timeout=5)
        assert released, "blocking runner timed out waiting for release"
        return self.return_code


class FailingCreateTriggerService:
    def __init__(self, *, session: Session) -> None:
        self.session = session

    def create_manual_crawl_job(self, **_: object) -> None:
        raise RuntimeError("mock create failed")


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


def _build_client(tmp_path: Path, *, runner: StubRunner, is_active: bool) -> tuple[TestClient, sessionmaker, object]:
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

    client = TestClient(app)
    return client, session_factory, engine


def test_manual_crawl_route_creates_new_manual_job_and_redirects(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers.get("location")
        assert location is not None
        assert location == "/admin/crawl-jobs?source_code=anhui_ggzy_zfcg&created_job_id=1"

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            created = jobs[0]
            assert created.source_site_id == source.id
            assert created.job_type == "manual"
            assert created.triggered_by == "admin_ui"
            assert created.retry_of_job_id is None

        assert len(runner.commands) == 1
        command_text = " ".join(runner.commands[0])
        assert "job_type=manual" in command_text
        assert "max_pages=7" in command_text

    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_source_sites_page_contains_manual_crawl_button(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, _, engine = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.get("/admin/source-sites")
        assert response.status_code == 200
        assert "手动抓取" in response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' in response.text
        assert 'name="return_to" value="source-sites"' in response.text
        assert 'href="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' not in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_is_post_only(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, _, engine = _build_client(tmp_path, runner=runner, is_active=True)
    try:
        response = client.get("/admin/sources/anhui_ggzy_zfcg/manual-crawl")
        assert response.status_code == 405
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_rejects_inactive_source_with_page_message(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=False)
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data={"return_to": "source-sites"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "来源未启用，无法手动抓取" in response.text
        assert "来源网站列表" in response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob)).all()
            assert jobs == []

        assert len(runner.commands) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_shows_create_failure_message_on_source_sites_page(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=True)
    failing_session = session_factory()
    app.dependency_overrides[get_source_crawl_trigger_service] = (
        lambda: FailingCreateTriggerService(session=failing_session)
    )
    try:
        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data={"return_to": "source-sites"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "手动抓取任务创建失败：mock create failed" in response.text
        assert "来源网站列表" in response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob)).all()
            assert jobs == []

        assert len(runner.commands) == 0
    finally:
        failing_session.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_rejects_when_same_source_already_has_active_job(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=True)
    service = CrawlJobService(session_factory=session_factory)
    try:
        active_job = service.create_job(
            source_code="anhui_ggzy_zfcg",
            job_type="manual",
            triggered_by="pytest-active",
        )
        service.start_job(active_job.id)

        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data={"return_to": "source-sites"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "已有进行中的抓取任务" in response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].id == active_job.id
            assert jobs[0].status == "running"

        assert len(runner.commands) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_route_rejects_double_submit_while_first_background_job_running(tmp_path: Path) -> None:
    release_event = Event()
    runner = BlockingRunner(release_event=release_event, return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=True)
    secondary_client = TestClient(app)
    try:
        first_response: dict[str, object] = {}

        def _send_first_request() -> None:
            try:
                first_response["value"] = client.post(
                    "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
                    data={"return_to": "source-sites"},
                    follow_redirects=False,
                )
            except Exception as exc:  # pragma: no cover - diagnostic guard for thread failure
                first_response["error"] = exc

        worker = Thread(target=_send_first_request)
        worker.start()
        assert runner.started_event.wait(timeout=5)

        with session_factory() as session:
            active_jobs = session.scalars(
                select(CrawlJob).where(CrawlJob.status.in_(["pending", "running"]))
            ).all()
            assert len(active_jobs) == 1
            assert active_jobs[0].status == "running"

        second_response = secondary_client.post(
            "/admin/sources/anhui_ggzy_zfcg/manual-crawl",
            data={"return_to": "source-sites"},
            follow_redirects=True,
        )
        assert second_response.status_code == 200
        assert "已有进行中的抓取任务" in second_response.text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].status == "running"

        assert len(runner.commands) == 1

        release_event.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert "error" not in first_response

        first = first_response.get("value")
        assert first is not None
        assert first.status_code == 303
        assert first.headers.get("location") == "/admin/crawl-jobs?source_code=anhui_ggzy_zfcg&created_job_id=1"

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].status == "succeeded"
            assert jobs[0].triggered_by == "admin_ui"
    finally:
        release_event.set()
        secondary_client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_database_url_for_bind_keeps_database_password() -> None:
    class DummyBind:
        url = make_url("postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1")

    assert _database_url_for_bind(DummyBind()) == "postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1"


def test_manual_crawl_background_marks_job_failed_when_source_missing(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    _, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=True)
    service = CrawlJobService(session_factory=session_factory)
    try:
        created = service.create_job(
            source_code="anhui_ggzy_zfcg",
            job_type="manual",
            triggered_by="admin_ui",
            message="manual crawl requested from admin ui",
        )

        _run_manual_crawl_job_background(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'manual_crawl_trigger.db'}",
            source_code="missing_source",
            crawl_job_id=created.id,
            max_pages=7,
            triggered_by="admin_ui",
            request_id="req-missing-source",
            command_runner=runner,
            project_root=tmp_path,
        )

        with session_factory() as session:
            job = session.get(CrawlJob, created.id)
            assert job is not None
            assert job.status == "failed"
            assert "triggered_by=admin_ui" in (job.message or "")
            assert "event=manual_crawl_background_source_missing" in (job.message or "")
            assert "failure_reason=后台任务启动失败：来源不存在或已被删除" in (job.message or "")
    finally:
        service.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_manual_crawl_background_logs_structured_failure_context(tmp_path: Path, monkeypatch, caplog) -> None:
    runner = StubRunner(return_code=0)
    _, session_factory, engine = _build_client(tmp_path, runner=runner, is_active=True)
    service = CrawlJobService(session_factory=session_factory)

    def fake_execute_manual_crawl_job(self, *, source, crawl_job_id: int, max_pages: int | None) -> None:
        _ = (self, source, crawl_job_id, max_pages)
        raise RuntimeError("background boom")

    monkeypatch.setattr(
        admin_sources_module.SourceCrawlTriggerService,
        "execute_manual_crawl_job",
        fake_execute_manual_crawl_job,
    )

    try:
        created = service.create_job(
            source_code="anhui_ggzy_zfcg",
            job_type="manual",
            triggered_by="admin_ui",
            message="manual crawl requested from admin ui",
        )

        with caplog.at_level(logging.INFO):
            _run_manual_crawl_job_background(
                database_url=f"sqlite+pysqlite:///{tmp_path / 'manual_crawl_trigger.db'}",
                source_code="anhui_ggzy_zfcg",
                crawl_job_id=created.id,
                max_pages=7,
                triggered_by="admin_ui",
                request_id="req-background-001",
                command_runner=runner,
                project_root=tmp_path,
            )

        failure_log = next(
            record for record in caplog.records if getattr(record, "event", "") == "manual_crawl_background_failed"
        )
        assert failure_log.levelno == logging.ERROR
        assert failure_log.source_code == "anhui_ggzy_zfcg"
        assert failure_log.crawl_job_id == created.id
        assert failure_log.job_type == "manual"
        assert failure_log.triggered_by == "admin_ui"
        assert failure_log.request_id == "req-background-001"

        with session_factory() as session:
            job = session.get(CrawlJob, created.id)
            assert job is not None
            assert job.status == "failed"
            assert "event=manual_crawl_background_failed" in (job.message or "")
            assert "failure_reason=后台任务执行失败：background boom" in (job.message or "")
    finally:
        service.close()
        app.dependency_overrides.clear()
        engine.dispose()
