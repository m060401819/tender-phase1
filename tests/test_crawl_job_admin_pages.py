from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.api.endpoints.sources import get_crawl_command_runner, get_crawl_job_dispatcher
from app.main import app
from app.models import CrawlError, CrawlJob
from app.repositories import SourceSiteRepository
from app.services import CrawlJobService, SourceCrawlTriggerService


@dataclass(slots=True)
class SeededAdminJobs:
    succeeded_job_id: int
    partial_job_id: int
    failed_job_id: int
    pending_job_id: int


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



def _insert_crawl_error(
    *,
    session_factory: sessionmaker,
    source_site_id: int,
    crawl_job_id: int,
    occurred_at: datetime,
) -> None:
    with session_factory() as session:
        next_id = int(session.scalar(select(func.max(CrawlError.id))) or 0) + 1
        session.add(
            CrawlError(
                id=next_id,
                source_site_id=source_site_id,
                crawl_job_id=crawl_job_id,
                raw_document_id=None,
                stage="parse",
                url="https://example.com/notice/detail?id=admin-test",
                error_type="AdminPageTestError",
                error_message="unit-test",
                traceback="",
                retryable=False,
                occurred_at=occurred_at,
                resolved=False,
            )
        )
        session.commit()



def _seed_jobs(session_factory: sessionmaker) -> SeededAdminJobs:
    service = CrawlJobService(session_factory=session_factory)
    now = datetime.now(timezone.utc)

    succeeded = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual", triggered_by="test")
    service.start_job(succeeded.id, started_at=now - timedelta(days=2))
    service.record_stats(
        succeeded.id,
        pages_fetched=5,
        documents_saved=5,
        notices_upserted=2,
        deduplicated_count=1,
    )
    service.finish_job(succeeded.id, status="succeeded", finished_at=now - timedelta(days=2, hours=-1))

    partial = service.create_job(source_code="example_source", job_type="backfill", triggered_by="test")
    service.start_job(partial.id, started_at=now - timedelta(days=1))
    _insert_crawl_error(
        session_factory=session_factory,
        source_site_id=partial.source_site_id,
        crawl_job_id=partial.id,
        occurred_at=now - timedelta(hours=2),
    )
    service.record_stats(
        partial.id,
        pages_fetched=2,
        documents_saved=2,
        notices_upserted=1,
        deduplicated_count=1,
        error_count=1,
    )
    service.finish_job(partial.id)

    failed = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual", triggered_by="test")
    service.start_job(failed.id, started_at=now - timedelta(hours=4))
    service.record_stats(
        failed.id,
        pages_fetched=1,
        documents_saved=1,
        notices_upserted=0,
        deduplicated_count=0,
        error_count=1,
    )
    service.finish_job(failed.id, status="failed", finished_at=now - timedelta(hours=3, minutes=30))

    pending = service.create_job(source_code="example_source", job_type="manual", triggered_by="test")

    return SeededAdminJobs(
        succeeded_job_id=succeeded.id,
        partial_job_id=partial.id,
        failed_job_id=failed.id,
        pending_job_id=pending.id,
    )



def _build_client(tmp_path: Path) -> tuple[TestClient, SeededAdminJobs, sessionmaker, StubRunner, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'crawl_job_admin.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    seeded = _seed_jobs(session_factory)
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
    return client, seeded, session_factory, runner, engine



def test_admin_crawl_jobs_list_page_supports_filter_and_pagination(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/crawl-jobs")
        assert response.status_code == 200
        assert "抓取任务看板" in response.text
        assert "仅看异常" in response.text
        assert "仅看今日失败" in response.text
        assert "实时进度" in response.text
        assert "已入队，等待启动" in response.text
        assert 'data-live-refresh="true"' in response.text
        assert f"/admin/crawl-jobs/{seeded.partial_job_id}" in response.text
        assert f"/admin/crawl-jobs/{seeded.failed_job_id}" in response.text
        assert f'action="/admin/crawl-jobs/{seeded.partial_job_id}/retry"' in response.text
        assert f'action="/admin/crawl-jobs/{seeded.failed_job_id}/retry"' in response.text

        filtered = client.get(
            "/admin/crawl-jobs",
            params={
                "source_code": "example_source",
                "status": "partial",
                "job_type": "backfill",
            },
        )
        assert filtered.status_code == 200
        assert "example_source" in filtered.text
        assert "anhui_ggzy_zfcg" not in filtered.text

        abnormal = client.get("/admin/crawl-jobs", params={"ops_filter": "abnormal"})
        assert abnormal.status_code == 200
        assert f"/admin/crawl-jobs/{seeded.partial_job_id}" in abnormal.text
        assert f"/admin/crawl-jobs/{seeded.failed_job_id}" in abnormal.text
        assert f"/admin/crawl-jobs/{seeded.succeeded_job_id}" not in abnormal.text

        today_failed = client.get("/admin/crawl-jobs", params={"ops_filter": "today_failed"})
        assert today_failed.status_code == 200
        assert f"/admin/crawl-jobs/{seeded.failed_job_id}" in today_failed.text
        assert f"/admin/crawl-jobs/{seeded.partial_job_id}" not in today_failed.text

        partial_only = client.get("/admin/crawl-jobs", params={"ops_filter": "partial"})
        assert partial_only.status_code == 200
        assert f"/admin/crawl-jobs/{seeded.partial_job_id}" in partial_only.text
        assert f"/admin/crawl-jobs/{seeded.failed_job_id}" not in partial_only.text

        paged = client.get(
            "/admin/crawl-jobs",
            params={"order_by": "id", "limit": 1, "offset": 1},
        )
        assert paged.status_code == 200
        assert "total=4 | limit=1 | offset=1" in paged.text
        assert f"/admin/crawl-jobs/{seeded.failed_job_id}" in paged.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_admin_crawl_job_detail_page_shows_json_region(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/admin/crawl-jobs/{seeded.partial_job_id}")
        assert response.status_code == 200
        assert f"任务详情 #{seeded.partial_job_id}" in response.text
        assert "实时抓取进度" in response.text
        assert "recent_crawl_error_count" in response.text
        assert "pages_scraped" in response.text
        assert "dedup_skipped" in response.text
        assert "queued_at" in response.text
        assert "picked_at" in response.text
        assert "heartbeat_at" in response.text
        assert "timeout_at" in response.text
        assert "lease_expires_at" in response.text
        assert "first_publish_date_seen" in response.text
        assert "last_publish_date_seen" in response.text
        assert '"source_code": "example_source"' in response.text
        assert '"recent_crawl_error_count": 1' in response.text

        not_found = client.get("/admin/crawl-jobs/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_crawl_job_detail_page_auto_refreshes_for_active_job(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/admin/crawl-jobs/{seeded.pending_job_id}")
        assert response.status_code == 200
        assert "实时抓取进度" in response.text
        assert "已入队，等待启动" in response.text
        assert 'data-live-refresh="true"' in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_crawl_job_detail_page_stops_auto_refresh_after_expired_pending_job_reconciled(tmp_path: Path) -> None:
    client, seeded, session_factory, _, engine = _build_client(tmp_path)
    try:
        with session_factory() as session:
            pending_job = session.get(CrawlJob, seeded.pending_job_id)
            assert pending_job is not None
            pending_job.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            pending_job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.commit()

        follow_up = client.get(f"/admin/crawl-jobs/{seeded.pending_job_id}")
        assert follow_up.status_code == 200
        assert 'data-live-refresh="true"' not in follow_up.text
        assert "timeout_stage=pending" in follow_up.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_crawl_jobs_can_retry_failed_job_and_show_result_link(tmp_path: Path) -> None:
    client, seeded, _, runner, engine = _build_client(tmp_path)
    try:
        retry_response = client.post(
            f"/admin/crawl-jobs/{seeded.failed_job_id}/retry",
            follow_redirects=False,
        )
        assert retry_response.status_code == 303
        location = retry_response.headers.get("location")
        assert location is not None
        assert location.startswith("/admin/crawl-jobs?retry_created_job_id=")
        assert len(runner.commands) == 1

        list_response = client.get(location)
        assert list_response.status_code == 200
        assert "重试任务已创建" in list_response.text
        assert "已重试" in list_response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
