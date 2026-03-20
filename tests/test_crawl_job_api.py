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
from app.main import app
from app.models import CrawlError
from app.services import CrawlJobService


@dataclass(slots=True)
class SeededJobs:
    succeeded_job_id: int
    running_job_id: int
    partial_job_id: int
    pending_job_id: int



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
        source_code="example_source",
        job_type="manual",
        triggered_by="test",
    )

    return SeededJobs(
        succeeded_job_id=succeeded.id,
        running_job_id=running.id,
        partial_job_id=partial.id,
        pending_job_id=pending.id,
    )



def _build_client(tmp_path: Path) -> tuple[TestClient, SeededJobs, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'crawl_job_api.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    seeded = _seed_jobs(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    return client, seeded, engine



def test_crawl_job_list_filters_sort_and_pagination(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
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



def test_crawl_job_list_default_order_by_started_at_desc(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get("/crawl-jobs", params={"limit": 4, "offset": 0})
        assert response.status_code == 200
        payload = response.json()

        ids = [item["id"] for item in payload["items"]]
        assert ids == [
            seeded.partial_job_id,
            seeded.running_job_id,
            seeded.succeeded_job_id,
            seeded.pending_job_id,
        ]
        assert payload["order_by"] == "started_at"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_crawl_job_detail_returns_core_fields_and_recent_error_count(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/crawl-jobs/{seeded.partial_job_id}")
        assert response.status_code == 200

        payload = response.json()
        assert payload["id"] == seeded.partial_job_id
        assert payload["source_code"] == "example_source"
        assert payload["job_type"] == "backfill"
        assert payload["status"] == "partial"
        assert payload["pages_fetched"] == 1
        assert payload["documents_saved"] == 1
        assert payload["notices_upserted"] == 1
        assert payload["deduplicated_count"] == 1
        assert payload["error_count"] == 2
        assert payload["recent_crawl_error_count"] == 1

        not_found = client.get("/crawl-jobs/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
