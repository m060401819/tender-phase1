from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Thread

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
import pytest

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.api.endpoints.sources import get_crawl_command_runner, get_crawl_job_dispatcher
from app.main import app
from app.models import CrawlError, CrawlJob
from app.repositories import SourceSiteRepository
from app.services.crawl_job_payloads import build_job_params_payload
from app.services import CrawlJobService, SourceCrawlTriggerService


@dataclass(slots=True)
class SeededJobs:
    succeeded_job_id: int
    running_job_id: int
    partial_job_id: int
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


class NoOpDispatcher:
    def dispatch(self, request, *, project_root: Path, database_url: str) -> None:  # type: ignore[no-untyped-def]
        _ = (request, project_root, database_url)



def _insert_crawl_error(
    *,
    session_factory: sessionmaker,
    source_site_id: int,
    crawl_job_id: int,
    occurred_at: datetime,
    error_type: str,
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
                url="https://example.com/notice/detail?id=test",
                error_type=error_type,
                error_message="unit-test",
                traceback="",
                retryable=False,
                occurred_at=occurred_at,
                resolved=False,
            )
        )
        session.commit()



def _seed_jobs(session_factory: sessionmaker) -> SeededJobs:
    service = CrawlJobService(session_factory=session_factory)
    now = datetime.now(timezone.utc)

    succeeded = service.create_job(
        source_code="anhui_ggzy_zfcg",
        job_type="manual",
        triggered_by="test",
    )
    service.start_job(succeeded.id, started_at=now - timedelta(days=3))
    service.record_stats(
        succeeded.id,
        pages_fetched=10,
        documents_saved=10,
        notices_upserted=4,
        deduplicated_count=2,
    )
    service.finish_job(succeeded.id, status="succeeded", finished_at=now - timedelta(days=3, hours=-1))

    running = service.create_job(
        source_code="anhui_ggzy_zfcg",
        job_type="scheduled",
        triggered_by="test",
    )
    service.start_job(running.id, started_at=now - timedelta(days=2))
    service.record_stats(
        running.id,
        pages_fetched=2,
        documents_saved=2,
        notices_upserted=1,
        deduplicated_count=1,
    )

    partial = service.create_job(
        source_code="example_source",
        job_type="backfill",
        triggered_by="test",
    )
    service.start_job(partial.id, started_at=now - timedelta(days=1))
    _insert_crawl_error(
        session_factory=session_factory,
        source_site_id=partial.source_site_id,
        crawl_job_id=partial.id,
        occurred_at=now - timedelta(hours=1),
        error_type="RecentApiTestError",
    )
    _insert_crawl_error(
        session_factory=session_factory,
        source_site_id=partial.source_site_id,
        crawl_job_id=partial.id,
        occurred_at=now - timedelta(days=20),
        error_type="OldApiTestError",
    )
    service.record_stats(
        partial.id,
        pages_fetched=1,
        documents_saved=1,
        notices_upserted=1,
        deduplicated_count=1,
        error_count=2,
    )
    service.finish_job(partial.id)

    pending = service.create_job(
        source_code="pending_source",
        job_type="manual",
        triggered_by="test",
    )

    return SeededJobs(
        succeeded_job_id=succeeded.id,
        running_job_id=running.id,
        partial_job_id=partial.id,
        pending_job_id=pending.id,
    )



def _build_client(tmp_path: Path) -> tuple[TestClient, SeededJobs, sessionmaker, StubRunner, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'crawl_job_api.db'}"
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



def test_crawl_job_list_filters_sort_and_pagination(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        by_source = client.get("/crawl-jobs", params={"source_code": "anhui_ggzy_zfcg"})
        assert by_source.status_code == 200
        payload = by_source.json()
        assert payload["total"] == 2
        assert all(item["source_code"] == "anhui_ggzy_zfcg" for item in payload["items"])

        by_status = client.get("/crawl-jobs", params={"status": "running"})
        assert by_status.status_code == 200
        status_payload = by_status.json()
        assert status_payload["total"] == 1
        assert status_payload["items"][0]["id"] == seeded.running_job_id

        by_job_type = client.get("/crawl-jobs", params={"job_type": "backfill"})
        assert by_job_type.status_code == 200
        type_payload = by_job_type.json()
        assert type_payload["total"] == 1
        assert type_payload["items"][0]["id"] == seeded.partial_job_id

        paged = client.get("/crawl-jobs", params={"order_by": "id", "limit": 2, "offset": 1})
        assert paged.status_code == 200
        page_payload = paged.json()
        assert page_payload["total"] == 4
        assert page_payload["limit"] == 2
        assert page_payload["offset"] == 1
        assert [item["id"] for item in page_payload["items"]] == [
            seeded.partial_job_id,
            seeded.running_job_id,
        ]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_crawl_job_list_default_order_by_started_at_desc_prioritizes_recently_queued_jobs(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        response = client.get("/crawl-jobs", params={"limit": 4, "offset": 0})
        assert response.status_code == 200
        payload = response.json()

        ids = [item["id"] for item in payload["items"]]
        assert ids == [
            seeded.pending_job_id,
            seeded.partial_job_id,
            seeded.running_job_id,
            seeded.succeeded_job_id,
        ]
        assert payload["order_by"] == "started_at"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_crawl_job_detail_returns_core_fields_and_recent_error_count(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/crawl-jobs/{seeded.partial_job_id}")
        assert response.status_code == 200

        payload = response.json()
        assert payload["id"] == seeded.partial_job_id
        assert payload["source_code"] == "example_source"
        assert payload["job_type"] == "backfill"
        assert payload["status"] == "partial"
        assert payload["queued_at"] is not None
        assert payload["picked_at"] is not None
        assert payload["timeout_at"] is None
        assert payload["pages_fetched"] == 1
        assert payload["documents_saved"] == 1
        assert payload["notices_upserted"] == 1
        assert payload["deduplicated_count"] == 1
        assert payload["error_count"] == 2
        assert payload["recent_crawl_error_count"] == 1
        assert payload["list_items_seen"] == 0
        assert payload["list_items_unique"] == 0
        assert payload["list_items_source_duplicates_skipped"] == 0
        assert payload["detail_pages_fetched"] == 0
        assert payload["records_inserted"] == 0
        assert payload["records_updated"] == 0
        assert payload["source_duplicates_suppressed"] == 0
        assert "job_params_json" in payload
        assert "runtime_stats_json" in payload
        assert "failure_reason" in payload

        not_found = client.get("/crawl-jobs/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_detail_keeps_expired_pending_job_recoverable(tmp_path: Path) -> None:
    client, seeded, session_factory, _, engine = _build_client(tmp_path)
    try:
        with session_factory() as session:
            job = session.get(CrawlJob, seeded.pending_job_id)
            assert job is not None
            job.picked_at = datetime.now(timezone.utc) - timedelta(minutes=2)
            job.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.commit()

        response = client.get(f"/crawl-jobs/{seeded.pending_job_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["picked_at"] is not None
        assert payload["timeout_at"] is not None
        assert payload["lease_expires_at"] is not None
        assert "timeout_stage=pending" not in (payload["message"] or "")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_detail_reconciles_expired_running_job(tmp_path: Path) -> None:
    client, seeded, session_factory, _, engine = _build_client(tmp_path)
    try:
        with session_factory() as session:
            job = session.get(CrawlJob, seeded.running_job_id)
            assert job is not None
            job.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
            job.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.commit()

        response = client.get(f"/crawl-jobs/{seeded.running_job_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "failed"
        assert payload["timeout_at"] is None
        assert payload["lease_expires_at"] is None
        assert payload["failure_reason"] == "任务心跳超时，执行进程可能已退出或卡死"
        assert payload["runtime_stats_json"]["timeout_stage"] == "running"
        assert "任务执行超时" in (payload["message"] or "")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _seed_failed_job_for_retry(session_factory: sessionmaker) -> int:
    now = datetime.now(timezone.utc)
    service = CrawlJobService(session_factory=session_factory)
    failed = service.create_job(
        source_code="ggzy_gov_cn_deal",
        job_type="manual",
        triggered_by="test",
    )
    service.start_job(failed.id, started_at=now - timedelta(hours=2))
    service.record_stats(
        failed.id,
        pages_fetched=1,
        documents_saved=1,
        notices_upserted=0,
        deduplicated_count=0,
        error_count=1,
    )
    service.finish_job(
        failed.id,
        status="failed",
        finished_at=now - timedelta(hours=1),
    )
    return failed.id


def test_crawl_job_retry_failed_job_creates_one_manual_retry(tmp_path: Path) -> None:
    client, _, session_factory, runner, engine = _build_client(tmp_path)
    try:
        failed_job_id = _seed_failed_job_for_retry(session_factory)
        response = client.post(f"/crawl-jobs/{failed_job_id}/retry", json={"triggered_by": "api-retry"})
        assert response.status_code == 201
        payload = response.json()
        assert payload["original_job_id"] == failed_job_id
        assert payload["retry_job"]["job_type"] == "manual_retry"
        assert payload["retry_job"]["retry_of_job_id"] == failed_job_id
        assert payload["retry_job"]["status"] == "pending"
        assert payload["retry_job"]["queued_at"] is not None
        assert payload["retry_job"]["picked_at"] is None
        assert len(runner.commands) == 1

        duplicate = client.post(f"/crawl-jobs/{failed_job_id}/retry", json={"triggered_by": "api-retry"})
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "job already retried"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_retry_partial_job_is_allowed(tmp_path: Path) -> None:
    client, seeded, _, runner, engine = _build_client(tmp_path)
    try:
        response = client.post(f"/crawl-jobs/{seeded.partial_job_id}/retry", json={"triggered_by": "api-retry"})
        assert response.status_code == 201
        payload = response.json()
        assert payload["original_job_id"] == seeded.partial_job_id
        assert payload["retry_job"]["job_type"] == "manual_retry"
        assert payload["retry_job"]["retry_of_job_id"] == seeded.partial_job_id
        assert payload["retry_job"]["status"] == "pending"
        assert len(runner.commands) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_retry_inherits_structured_job_params_without_parsing_message(tmp_path: Path) -> None:
    client, _, session_factory, runner, engine = _build_client(tmp_path)
    try:
        service = CrawlJobService(session_factory=session_factory)
        now = datetime.now(timezone.utc)
        failed = service.create_job(
            source_code="ggzy_gov_cn_deal",
            job_type="backfill",
            triggered_by="pytest-backfill",
            job_params_json=build_job_params_payload(
                source_code="ggzy_gov_cn_deal",
                job_type="backfill",
                triggered_by="pytest-backfill",
                max_pages=123,
                backfill_year=2026,
            ),
            message="这是一条人工摘要，不包含任何可解析参数",
        )
        service.start_job(failed.id, started_at=now - timedelta(hours=2), message="任务执行中")
        service.finish_job(
            failed.id,
            status="failed",
            failure_reason="页面获取失败：示例异常",
            message="任务失败：页面获取失败：示例异常",
        )

        response = client.post(f"/crawl-jobs/{failed.id}/retry", json={"triggered_by": "api-retry"})
        assert response.status_code == 201
        assert len(runner.commands) == 1

        command_text = " ".join(runner.commands[0])
        assert "backfill_year=2026" in command_text
        assert "max_pages=123" in command_text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_retry_succeeded_job_is_rejected(tmp_path: Path) -> None:
    client, seeded, _, _, engine = _build_client(tmp_path)
    try:
        response = client.post(f"/crawl-jobs/{seeded.succeeded_job_id}/retry", json={"triggered_by": "api-retry"})
        assert response.status_code == 400
        assert response.json()["detail"] == "only failed or partial job can be retried"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_retry_not_found_returns_404(tmp_path: Path) -> None:
    client, _, _, _, engine = _build_client(tmp_path)
    try:
        response = client.post("/crawl-jobs/999999/retry", json={"triggered_by": "api-retry"})
        assert response.status_code == 404
        assert response.json()["detail"] == "crawl_job not found"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_job_retry_concurrent_requests_return_conflict_instead_of_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, session_factory, runner, engine = _build_client(tmp_path)
    secondary_client = TestClient(app)
    barrier = Barrier(2)
    original_create_job_in_session = CrawlJobService.create_job_in_session
    try:
        failed_job_id = _seed_failed_job_for_retry(session_factory)
        app.dependency_overrides[get_crawl_job_dispatcher] = lambda: NoOpDispatcher()

        def _concurrent_create_job_in_session(self, session, **kwargs):  # type: ignore[no-untyped-def]
            retry_of_job_id = kwargs.get("retry_of_job_id")
            if retry_of_job_id is not None:
                barrier.wait(timeout=5)
            return original_create_job_in_session(self, session, **kwargs)

        monkeypatch.setattr(CrawlJobService, "create_job_in_session", _concurrent_create_job_in_session)

        first_response: dict[str, object] = {}

        def _send_first_request() -> None:
            try:
                first_response["value"] = client.post(
                    f"/crawl-jobs/{failed_job_id}/retry",
                    json={"triggered_by": "api-retry-thread-a"},
                )
            except Exception as exc:  # pragma: no cover - diagnostic guard for thread failure
                first_response["error"] = exc

        worker = Thread(target=_send_first_request)
        worker.start()

        second = secondary_client.post(
            f"/crawl-jobs/{failed_job_id}/retry",
            json={"triggered_by": "api-retry-thread-b"},
        )

        worker.join(timeout=5)
        assert not worker.is_alive()
        assert "error" not in first_response

        first = first_response.get("value")
        assert first is not None

        responses = [first, second]
        status_codes = sorted(response.status_code for response in responses)
        assert status_codes == [201, 409]

        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["detail"] == "job already retried"

        with session_factory() as session:
            retry_jobs = session.scalars(
                select(CrawlJob)
                .where(CrawlJob.retry_of_job_id == failed_job_id)
                .order_by(CrawlJob.id.asc())
            ).all()
            assert len(retry_jobs) == 1
            assert retry_jobs[0].job_type == "manual_retry"
            assert retry_jobs[0].status == "pending"

        assert len(runner.commands) == 0
    finally:
        secondary_client.close()
        app.dependency_overrides.clear()
        engine.dispose()
