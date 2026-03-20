from __future__ import annotations

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
            assert job.pages_fetched == 0
            assert job.documents_saved == 0
            assert job.notices_upserted == 0
            assert job.deduplicated_count == 0
            assert job.error_count == 0
    finally:
        service.close()


def test_crawl_job_start_record_stats_and_finish_success(tmp_path: Path) -> None:
    service = _make_service(tmp_path / "crawl_job_success.db")
    try:
        created = service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual", triggered_by="pytest")

        running = service.start_job(created.id)
        assert running is not None
        assert running.status == "running"
        assert running.started_at is not None
        assert running.finished_at is None

        updated = service.record_stats(
            created.id,
            pages_fetched=7,
            documents_saved=7,
            notices_upserted=3,
            deduplicated_count=2,
            error_count=0,
        )
        assert updated is not None
        assert updated.pages_fetched == 7
        assert updated.documents_saved == 7
        assert updated.notices_upserted == 3
        assert updated.deduplicated_count == 2
        assert updated.error_count == 0

        finished = service.finish_job(created.id)
        assert finished is not None
        assert finished.status == "succeeded"
        assert finished.finished_at is not None
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
