from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlError, CrawlJob, RawDocument, SourceSite, TenderNotice


def _seed_data(session_factory: sessionmaker) -> None:
    base_dt = datetime.combine(datetime.now(timezone.utc).date(), time(hour=12), tzinfo=timezone.utc)

    with session_factory() as session:
        source_1 = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="stats api test source 1",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        source_2 = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="stats api test source 2",
            is_active=False,
            supports_js_render=False,
            crawl_interval_minutes=30,
        )
        source_3 = SourceSite(
            id=3,
            code="backup_source",
            name="Backup Source",
            base_url="https://backup.example.com/",
            description="stats api test source 3",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=120,
        )
        session.add_all([source_1, source_2, source_3])

        jobs = [
            CrawlJob(
                id=701,
                source_site_id=source_1.id,
                job_type="manual",
                status="running",
                triggered_by="test",
                started_at=base_dt,
                finished_at=None,
                pages_fetched=1,
                documents_saved=1,
                notices_upserted=1,
                deduplicated_count=0,
                error_count=0,
                message="running job",
                created_at=base_dt,
                updated_at=base_dt,
            ),
            CrawlJob(
                id=702,
                source_site_id=source_1.id,
                job_type="manual",
                status="failed",
                triggered_by="test",
                started_at=base_dt - timedelta(days=1),
                finished_at=base_dt - timedelta(days=1, hours=-1),
                pages_fetched=2,
                documents_saved=2,
                notices_upserted=1,
                deduplicated_count=0,
                error_count=1,
                message="failed job",
                created_at=base_dt - timedelta(days=1),
                updated_at=base_dt - timedelta(days=1),
            ),
            CrawlJob(
                id=703,
                source_site_id=source_2.id,
                job_type="backfill",
                status="partial",
                triggered_by="test",
                started_at=base_dt - timedelta(days=2),
                finished_at=base_dt - timedelta(days=2, hours=-1),
                pages_fetched=3,
                documents_saved=3,
                notices_upserted=2,
                deduplicated_count=1,
                error_count=1,
                message="partial job",
                created_at=base_dt - timedelta(days=2),
                updated_at=base_dt - timedelta(days=2),
            ),
            CrawlJob(
                id=704,
                source_site_id=source_3.id,
                job_type="scheduled",
                status="succeeded",
                triggered_by="test",
                started_at=base_dt - timedelta(days=8),
                finished_at=base_dt - timedelta(days=8, hours=-1),
                pages_fetched=1,
                documents_saved=1,
                notices_upserted=1,
                deduplicated_count=0,
                error_count=0,
                message="old succeeded job",
                created_at=base_dt - timedelta(days=8),
                updated_at=base_dt - timedelta(days=8),
            ),
        ]
        session.add_all(jobs)

        notices = [
            TenderNotice(
                id=101,
                source_site_id=source_1.id,
                external_id="AH-STATS-001",
                project_code="STATS-001",
                dedup_hash="dedup-stats-001",
                title="统计公告-今天",
                notice_type="announcement",
                issuer="issuer-a",
                region="合肥",
                published_at=base_dt,
                deadline_at=base_dt + timedelta(days=7),
                budget_amount=None,
                budget_currency="CNY",
                summary="today notice",
                first_published_at=base_dt,
                latest_published_at=base_dt,
                current_version_id=None,
                created_at=base_dt,
                updated_at=base_dt,
            ),
            TenderNotice(
                id=102,
                source_site_id=source_1.id,
                external_id="AH-STATS-002",
                project_code="STATS-002",
                dedup_hash="dedup-stats-002",
                title="统计公告-两天前",
                notice_type="announcement",
                issuer="issuer-b",
                region="芜湖",
                published_at=base_dt - timedelta(days=2),
                deadline_at=base_dt + timedelta(days=5),
                budget_amount=None,
                budget_currency="CNY",
                summary="day-2 notice",
                first_published_at=base_dt - timedelta(days=2),
                latest_published_at=base_dt - timedelta(days=2),
                current_version_id=None,
                created_at=base_dt - timedelta(days=2),
                updated_at=base_dt - timedelta(days=2),
            ),
            TenderNotice(
                id=103,
                source_site_id=source_2.id,
                external_id="EX-STATS-003",
                project_code="STATS-003",
                dedup_hash="dedup-stats-003",
                title="统计公告-七天外",
                notice_type="change",
                issuer="issuer-c",
                region="南京",
                published_at=base_dt - timedelta(days=9),
                deadline_at=base_dt - timedelta(days=1),
                budget_amount=None,
                budget_currency="CNY",
                summary="old notice",
                first_published_at=base_dt - timedelta(days=9),
                latest_published_at=base_dt - timedelta(days=9),
                current_version_id=None,
                created_at=base_dt - timedelta(days=9),
                updated_at=base_dt - timedelta(days=9),
            ),
        ]
        session.add_all(notices)

        raw_documents = [
            RawDocument(
                id=401,
                source_site_id=source_1.id,
                crawl_job_id=701,
                url="https://ggzy.ah.gov.cn/raw/401",
                normalized_url="https://ggzy.ah.gov.cn/raw/401",
                url_hash="raw-stats-401",
                content_hash="content-stats-401",
                document_type="html",
                http_status=200,
                mime_type="text/html",
                charset="utf-8",
                title="raw-401",
                fetched_at=base_dt,
                storage_uri="file:///tmp/raw/stats-401.html",
                content_length=123,
                is_duplicate_url=False,
                is_duplicate_content=False,
                extra_meta=None,
            ),
            RawDocument(
                id=402,
                source_site_id=source_2.id,
                crawl_job_id=None,
                url="https://example.com/raw/402",
                normalized_url="https://example.com/raw/402",
                url_hash="raw-stats-402",
                content_hash="content-stats-402",
                document_type="json",
                http_status=200,
                mime_type="application/json",
                charset="utf-8",
                title="raw-402",
                fetched_at=base_dt - timedelta(days=1),
                storage_uri="file:///tmp/raw/stats-402.json",
                content_length=222,
                is_duplicate_url=False,
                is_duplicate_content=False,
                extra_meta=None,
            ),
        ]
        session.add_all(raw_documents)

        errors = [
            CrawlError(
                id=501,
                source_site_id=source_1.id,
                crawl_job_id=701,
                raw_document_id=401,
                stage="parse",
                url="https://ggzy.ah.gov.cn/raw/401",
                error_type="ParserError",
                error_message="parse failed today",
                traceback="tb-501",
                retryable=False,
                occurred_at=base_dt,
                resolved=False,
                created_at=base_dt,
                updated_at=base_dt,
            ),
            CrawlError(
                id=502,
                source_site_id=source_1.id,
                crawl_job_id=702,
                raw_document_id=None,
                stage="fetch",
                url="https://ggzy.ah.gov.cn/list?page=2",
                error_type="FetchTimeout",
                error_message="timeout day-1",
                traceback=None,
                retryable=True,
                occurred_at=base_dt - timedelta(days=1),
                resolved=False,
                created_at=base_dt - timedelta(days=1),
                updated_at=base_dt - timedelta(days=1),
            ),
            CrawlError(
                id=503,
                source_site_id=source_2.id,
                crawl_job_id=704,
                raw_document_id=None,
                stage="persist",
                url="https://example.com/raw/old",
                error_type="PersistConflict",
                error_message="old error",
                traceback="tb-503",
                retryable=False,
                occurred_at=base_dt - timedelta(days=9),
                resolved=False,
                created_at=base_dt - timedelta(days=9),
                updated_at=base_dt - timedelta(days=9),
            ),
        ]
        session.add_all(errors)

        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, sessionmaker, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'stats_overview_api.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_data(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, session_factory, engine


def test_stats_overview_api_returns_counts_trends_and_recent_summaries(tmp_path: Path) -> None:
    client, _, engine = _build_client(tmp_path)
    try:
        response = client.get("/stats/overview")
        assert response.status_code == 200
        payload = response.json()

        assert payload["source_count"] == 3
        assert payload["active_source_count"] == 2
        assert payload["crawl_job_count"] == 4
        assert payload["crawl_job_running_count"] == 1
        assert payload["notice_count"] == 3
        assert payload["today_new_notice_count"] == 1
        assert payload["recent_24h_new_notice_count"] == 1
        assert payload["raw_document_count"] == 2
        assert payload["crawl_error_count"] == 3

        assert len(payload["recent_7d_crawl_job_counts"]) == 7
        assert len(payload["recent_7d_notice_counts"]) == 7
        assert len(payload["recent_7d_crawl_error_counts"]) == 7

        today = datetime.now(timezone.utc).date()
        d0 = today.isoformat()
        d1 = (today - timedelta(days=1)).isoformat()
        d2 = (today - timedelta(days=2)).isoformat()

        job_map = {item["date"]: item["count"] for item in payload["recent_7d_crawl_job_counts"]}
        assert job_map[d0] == 1
        assert job_map[d1] == 1
        assert job_map[d2] == 1

        notice_map = {item["date"]: item["count"] for item in payload["recent_7d_notice_counts"]}
        assert notice_map[d0] == 1
        assert notice_map[d2] == 1

        error_map = {item["date"]: item["count"] for item in payload["recent_7d_crawl_error_counts"]}
        assert error_map[d0] == 1
        assert error_map[d1] == 1

        recent_jobs = payload["recent_failed_or_partial_jobs"]
        assert [item["id"] for item in recent_jobs][:2] == [702, 703]

        recent_errors = payload["recent_crawl_errors"]
        assert [item["id"] for item in recent_errors][:2] == [501, 502]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_stats_overview_reconciles_expired_running_job(tmp_path: Path) -> None:
    client, session_factory, engine = _build_client(tmp_path)
    try:
        with session_factory() as session:
            running_job = session.get(CrawlJob, 701)
            assert running_job is not None
            running_job.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
            running_job.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            running_job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.commit()

        response = client.get("/stats/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["crawl_job_running_count"] == 0

        with session_factory() as session:
            refreshed = session.scalar(select(CrawlJob).where(CrawlJob.id == 701))
            assert refreshed is not None
            assert refreshed.status == "failed"
            assert refreshed.failure_reason == "任务心跳超时，执行进程可能已退出或卡死"
            assert refreshed.runtime_stats_json is not None
            assert refreshed.runtime_stats_json["timeout_stage"] == "running"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
