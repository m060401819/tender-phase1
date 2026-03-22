from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
            description="dashboard admin source 1",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        source_2 = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="dashboard admin source 2",
            is_active=False,
            supports_js_render=False,
            crawl_interval_minutes=30,
        )
        session.add_all([source_1, source_2])

        session.add_all(
            [
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
            ]
        )

        session.add_all(
            [
                TenderNotice(
                    id=101,
                    source_site_id=source_1.id,
                    external_id="AH-DASH-001",
                    project_code="DASH-001",
                    dedup_hash="dedup-dash-001",
                    title="dashboard notice 1",
                    notice_type="announcement",
                    issuer="issuer-a",
                    region="合肥",
                    published_at=base_dt,
                    deadline_at=base_dt + timedelta(days=1),
                    budget_amount=None,
                    budget_currency="CNY",
                    summary=None,
                    first_published_at=base_dt,
                    latest_published_at=base_dt,
                    current_version_id=None,
                    created_at=base_dt,
                    updated_at=base_dt,
                ),
                TenderNotice(
                    id=102,
                    source_site_id=source_2.id,
                    external_id="EX-DASH-002",
                    project_code="DASH-002",
                    dedup_hash="dedup-dash-002",
                    title="dashboard notice 2",
                    notice_type="result",
                    issuer="issuer-b",
                    region="南京",
                    published_at=base_dt - timedelta(days=2),
                    deadline_at=None,
                    budget_amount=None,
                    budget_currency="CNY",
                    summary=None,
                    first_published_at=base_dt - timedelta(days=2),
                    latest_published_at=base_dt - timedelta(days=2),
                    current_version_id=None,
                    created_at=base_dt - timedelta(days=2),
                    updated_at=base_dt - timedelta(days=2),
                ),
            ]
        )

        session.add(
            RawDocument(
                id=401,
                source_site_id=source_1.id,
                crawl_job_id=701,
                url="https://ggzy.ah.gov.cn/raw/401",
                normalized_url="https://ggzy.ah.gov.cn/raw/401",
                url_hash="raw-dash-401",
                content_hash="content-dash-401",
                document_type="html",
                http_status=200,
                mime_type="text/html",
                charset="utf-8",
                title="raw dashboard 401",
                fetched_at=base_dt,
                storage_uri="file:///tmp/raw/dash-401.html",
                content_length=123,
                is_duplicate_url=False,
                is_duplicate_content=False,
                extra_meta=None,
            )
        )

        session.add_all(
            [
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
            ]
        )

        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'dashboard_admin_pages.db'}"
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
    return client, engine


def test_admin_dashboard_page_shows_counts_trends_links_and_recent_items(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "系统总览 Dashboard" in response.text
        assert "source_count" in response.text
        assert "crawl_job_count" in response.text
        assert "notice_count" in response.text
        assert "today_new_notice_count" in response.text
        assert "recent_24h_new_notice_count" in response.text
        assert "raw_document_count" in response.text
        assert "crawl_error_count" in response.text
        assert "active=1" in response.text
        assert "running=1" in response.text
        assert "最近24小时新增" in response.text

        assert "最近 7 天趋势" in response.text
        assert "最近失败/部分成功任务" in response.text
        assert "最近错误事件" in response.text

        assert "/admin/sources" in response.text
        assert "/admin/crawl-jobs" in response.text
        assert "/admin/notices" in response.text
        assert "/admin/raw-documents" in response.text
        assert "/admin/crawl-errors" in response.text

        assert "/admin/crawl-jobs/702" in response.text
        assert "/admin/crawl-jobs/703" in response.text
        assert "/admin/crawl-errors/501" in response.text
        assert "/admin/crawl-errors/502" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
