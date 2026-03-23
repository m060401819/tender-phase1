from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

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
            assert job.heartbeat_at is None
            assert job.timeout_at is None
            assert job.lease_expires_at is None
            assert job.job_params_json is None
            assert job.runtime_stats_json is None
            assert job.failure_reason is None
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


def test_crawl_job_claim_pending_job_sets_dispatch_lease_and_allows_reclaim_after_timeout(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_claim_pending.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        first_claim_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        claimed = service.claim_pending_job(created.id, picked_at=first_claim_at, lease_seconds=1)
        assert claimed is not None
        assert claimed.status == "pending"
        assert claimed.picked_at is not None
        assert claimed.picked_at.replace(tzinfo=timezone.utc) == first_claim_at
        assert claimed.timeout_at is not None

        refreshed = service.get_job(created.id)
        assert refreshed is not None
        assert refreshed.status == "pending"
        assert refreshed.picked_at is not None
        assert refreshed.picked_at.replace(tzinfo=timezone.utc) == first_claim_at
        assert refreshed.finished_at is None

        expired = service.reconcile_expired_jobs(now=first_claim_at + timedelta(minutes=1))
        assert expired == []

        reclaimed = service.claim_pending_job(
            created.id,
            picked_at=first_claim_at + timedelta(minutes=2),
            lease_seconds=30,
        )
        assert reclaimed is not None
        assert reclaimed.status == "pending"
        assert reclaimed.picked_at is not None
        assert reclaimed.picked_at.replace(tzinfo=timezone.utc) == first_claim_at + timedelta(minutes=2)
        assert reclaimed.timeout_at is not None
    finally:
        service.close()


def test_crawl_job_start_is_atomic_under_concurrency(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_start_atomic.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        barrier = Barrier(3)
        first_started_at = datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc)
        second_started_at = first_started_at + timedelta(seconds=1)

        def _start_job(started_at: datetime):
            barrier.wait(timeout=5)
            return service.start_job(created.id, started_at=started_at, message=f"started_at={started_at.isoformat()}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_1 = executor.submit(_start_job, first_started_at)
            future_2 = executor.submit(_start_job, second_started_at)
            barrier.wait(timeout=5)
            results = [future_1.result(timeout=5), future_2.result(timeout=5)]

        started = [item for item in results if item is not None]
        rejected = [item for item in results if item is None]
        assert len(started) == 1
        assert len(rejected) == 1

        winner = started[0]
        assert winner.status == "running"
        assert winner.started_at is not None
        assert winner.message in {
            f"started_at={first_started_at.isoformat()}",
            f"started_at={second_started_at.isoformat()}",
        }

        refreshed = service.get_job(created.id)
        assert refreshed is not None
        assert refreshed.status == "running"
        assert refreshed.started_at == winner.started_at
        assert refreshed.message == winner.message
    finally:
        service.close()


def test_crawl_job_start_second_attempt_returns_none_when_job_already_running(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_start_running_once.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        first_started_at = datetime(2026, 3, 22, 9, 0, tzinfo=timezone.utc)
        first = service.start_job(
            created.id,
            started_at=first_started_at,
            message="worker=first",
        )
        assert first is not None
        assert first.status == "running"

        second = service.start_job(
            created.id,
            started_at=first_started_at + timedelta(minutes=5),
            message="worker=second",
        )
        assert second is None

        refreshed = service.get_job(created.id)
        assert refreshed is not None
        assert refreshed.status == "running"
        assert refreshed.started_at is not None
        assert refreshed.started_at.replace(tzinfo=timezone.utc) == first_started_at
        assert refreshed.message == "worker=first"
    finally:
        service.close()


def test_crawl_job_expired_running_job_requires_reconcile_instead_of_running_takeover(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_expired_running_reconcile.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual")
        running = service.start_job(created.id)
        assert running is not None

        expired_heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        service.heartbeat_job(created.id, heartbeat_at=expired_heartbeat_at, lease_seconds=1)

        duplicate_start = service.start_job(
            created.id,
            started_at=expired_heartbeat_at + timedelta(minutes=1),
            message="worker=takeover",
        )
        assert duplicate_start is None

        expired = service.reconcile_expired_jobs(now=expired_heartbeat_at + timedelta(seconds=2))
        assert [item.id for item in expired] == [created.id]

        refreshed = service.get_job(created.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.failure_reason == "任务心跳超时，执行进程可能已退出或卡死"
        assert refreshed.runtime_stats_json is not None
        assert refreshed.runtime_stats_json["timeout_stage"] == "running"
        assert "任务执行超时" in (refreshed.message or "")

        restarted = service.start_job(
            created.id,
            started_at=expired_heartbeat_at + timedelta(minutes=2),
            message="worker=restart-after-failed",
        )
        assert restarted is None
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
        assert refreshed.failure_reason == "任务心跳超时，执行进程可能已退出或卡死"
        assert refreshed.runtime_stats_json is not None
        assert refreshed.runtime_stats_json["timeout_stage"] == "running"
        assert "任务执行超时" in (refreshed.message or "")
    finally:
        service.close()
