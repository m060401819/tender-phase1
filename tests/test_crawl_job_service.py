from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.db.base import Base
from app.services import CrawlJobService


def _make_service(db_path: Path) -> CrawlJobService:
    database_url = f"sqlite+pysqlite:///{db_path}"
    bootstrap_engine = create_engine(database_url)
    Base.metadata.create_all(bootstrap_engine)
    bootstrap_engine.dispose()
    return CrawlJobService.from_database_url(database_url)


def test_crawl_job_create_supports_all_job_types(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_types.db")
    try:
        for job_type in ["manual", "scheduled", "backfill"]:
            job = service.create_job(source_code=f"source_{job_type}", job_type=job_type)
            assert job.job_type == job_type
            assert job.status == "pending"
            assert job.queued_at is not None
            assert job.picked_at is None
            assert job.pages_fetched == 0
            assert job.documents_saved == 0
            assert job.notices_upserted == 0
            assert job.deduplicated_count == 0
            assert job.error_count == 0
            assert job.list_items_seen == 0
            assert job.list_items_unique == 0
            assert job.list_items_source_duplicates_skipped == 0
            assert job.detail_pages_fetched == 0
            assert job.records_inserted == 0
            assert job.records_updated == 0
            assert job.source_duplicates_suppressed == 0
            assert job.heartbeat_at is not None
            assert job.timeout_at is not None
            assert job.lease_expires_at is not None
    finally:
        service.close()


def test_crawl_job_start_record_stats_and_finish_success(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_success.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual", triggered_by="pytest")

        running = service.start_job(created.id)
        assert running is not None
        assert running.status == "running"
        assert running.queued_at is not None
        assert running.picked_at is not None
        assert running.started_at is not None
        assert running.finished_at is None
        assert running.heartbeat_at is not None
        assert running.timeout_at is not None
        assert running.lease_expires_at is not None

        updated = service.record_stats(
            created.id,
            pages_fetched=7,
            documents_saved=7,
            notices_upserted=3,
            deduplicated_count=2,
            error_count=0,
            list_items_seen=12,
            list_items_unique=10,
            list_items_source_duplicates_skipped=2,
            detail_pages_fetched=10,
            records_inserted=14,
            records_updated=3,
            source_duplicates_suppressed=1,
        )
        assert updated is not None
        assert updated.pages_fetched == 7
        assert updated.documents_saved == 7
        assert updated.notices_upserted == 3
        assert updated.deduplicated_count == 2
        assert updated.error_count == 0
        assert updated.list_items_seen == 12
        assert updated.list_items_unique == 10
        assert updated.list_items_source_duplicates_skipped == 2
        assert updated.detail_pages_fetched == 10
        assert updated.records_inserted == 14
        assert updated.records_updated == 3
        assert updated.source_duplicates_suppressed == 1

        finished = service.finish_job(created.id)
        assert finished is not None
        assert finished.status == "succeeded"
        assert finished.finished_at is not None
        assert finished.heartbeat_at is not None
        assert finished.timeout_at is None
        assert finished.lease_expires_at is None
    finally:
        service.close()


def test_crawl_job_finish_failed(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_failed.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        service.start_job(created.id)

        finished = service.finish_job(created.id, status="failed", message="network timeout")
        assert finished is not None
        assert finished.status == "failed"
        assert finished.finished_at is not None
        assert finished.message == "network timeout"
        assert finished.timeout_at is None
        assert finished.lease_expires_at is None
    finally:
        service.close()


def test_crawl_job_finish_partial_when_errors_exist(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_partial.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        service.start_job(created.id)
        service.record_stats(created.id, pages_fetched=2, documents_saved=2, error_count=1)

        finished = service.finish_job(created.id)
        assert finished is not None
        assert finished.status == "partial"
        assert finished.error_count == 1
    finally:
        service.close()


def test_crawl_job_reconcile_expired_pending_job_marks_failed(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_expired_pending.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        expired = service.reconcile_expired_jobs(now=datetime.now(timezone.utc) + timedelta(minutes=5))
        assert [item.id for item in expired] == [created.id]

        refreshed = service.get_job(created.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.finished_at is not None
        assert refreshed.timeout_at is None
        assert refreshed.lease_expires_at is None
        assert "failure_reason=任务启动超时" in (refreshed.message or "")
        assert "timeout_stage=pending" in (refreshed.message or "")
    finally:
        service.close()


def test_crawl_job_reconcile_expired_running_job_marks_failed(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_expired_running.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        service.start_job(created.id)
        heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        service.heartbeat_job(created.id, heartbeat_at=heartbeat_at, lease_seconds=1)

        expired = service.reconcile_expired_jobs(now=heartbeat_at + timedelta(seconds=2))
        assert [item.id for item in expired] == [created.id]

        refreshed = service.get_job(created.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.finished_at is not None
        assert refreshed.timeout_at is None
        assert refreshed.lease_expires_at is None
        assert "timeout_stage=running" in (refreshed.message or "")
        assert "failure_reason=任务心跳超时" in (refreshed.message or "")
    finally:
        service.close()
