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
class SeededAdminJobs:
    succeeded_job_id: int
    partial_job_id: int
    pending_job_id: int



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

    pending = service.create_job(source_code="example_source", job_type="manual", triggered_by="test")

    return SeededAdminJobs(
        succeeded_job_id=succeeded.id,
        partial_job_id=partial.id,
        pending_job_id=pending.id,
    )



def _build_client(tmp_path: Path) -> tuple[TestClient, SeededAdminJobs, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'crawl_job_admin.db'}"
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



def test_admin_crawl_jobs_list_page_supports_filter_and_pagination(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/crawl-jobs")
        assert response.status_code == 200
        assert "抓取任务看板" in response.text
        assert f"/admin/crawl-jobs/{seeded.partial_job_id}" in response.text

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

        paged = client.get(
            "/admin/crawl-jobs",
            params={"order_by": "id", "limit": 1, "offset": 1},
        )
        assert paged.status_code == 200
        assert "total=3 | limit=1 | offset=1" in paged.text
        assert f"/admin/crawl-jobs/{seeded.partial_job_id}" in paged.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_admin_crawl_job_detail_page_shows_json_region(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/admin/crawl-jobs/{seeded.partial_job_id}")
        assert response.status_code == 200
        assert f"任务详情 #{seeded.partial_job_id}" in response.text
        assert "recent_crawl_error_count" in response.text
        assert '"source_code": "example_source"' in response.text
        assert '"recent_crawl_error_count": 1' in response.text

        not_found = client.get("/admin/crawl-jobs/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
