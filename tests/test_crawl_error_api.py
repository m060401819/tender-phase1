from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlError, CrawlJob, NoticeVersion, RawDocument, SourceSite, TenderNotice


def _seed_data(session_factory: sessionmaker) -> None:
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        source_anhui = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="crawl error api test",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        source_example = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="crawl error api test other",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        session.add_all([source_anhui, source_example])

        job_1 = CrawlJob(
            id=701,
            source_site_id=source_anhui.id,
            job_type="manual",
            status="partial",
            triggered_by="test",
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=2),
            pages_fetched=2,
            documents_saved=2,
            notices_upserted=1,
            deduplicated_count=0,
            error_count=1,
            message="api test job 1",
        )
        job_2 = CrawlJob(
            id=702,
            source_site_id=source_anhui.id,
            job_type="manual",
            status="failed",
            triggered_by="test",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
            pages_fetched=1,
            documents_saved=1,
            notices_upserted=0,
            deduplicated_count=0,
            error_count=1,
            message="api test job 2",
        )
        job_3 = CrawlJob(
            id=703,
            source_site_id=source_example.id,
            job_type="backfill",
            status="partial",
            triggered_by="test",
            started_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=20),
            pages_fetched=1,
            documents_saved=1,
            notices_upserted=0,
            deduplicated_count=0,
            error_count=1,
            message="api test job 3",
        )
        session.add_all([job_1, job_2, job_3])

        raw_doc = RawDocument(
            id=401,
            source_site_id=source_anhui.id,
            crawl_job_id=job_1.id,
            url="https://ggzy.ah.gov.cn/notice/crawl-error-api",
            normalized_url="https://ggzy.ah.gov.cn/notice/crawl-error-api",
            url_hash="raw-crawl-error-api-001",
            content_hash="content-crawl-error-api-001",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="crawl error api raw",
            fetched_at=now - timedelta(hours=3),
            storage_uri="file:///tmp/raw/crawl-error-api-001.html",
            content_length=1200,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "crawl-error-api"},
        )
        session.add(raw_doc)

        notice = TenderNotice(
            id=101,
            source_site_id=source_anhui.id,
            external_id="AH-ERR-001",
            project_code="ERR-001",
            dedup_hash="dedup-err-001",
            title="抓取错误关联测试公告",
            notice_type="announcement",
            issuer="安徽电力公司",
            region="合肥",
            published_at=now - timedelta(days=1),
            deadline_at=now + timedelta(days=2),
            budget_amount=Decimal("1000.00"),
            budget_currency="CNY",
            summary="crawl error link test",
            first_published_at=now - timedelta(days=1),
            latest_published_at=now - timedelta(days=1),
            current_version_id=None,
        )
        session.add(notice)

        version = NoticeVersion(
            id=201,
            notice_id=notice.id,
            raw_document_id=raw_doc.id,
            version_no=1,
            is_current=True,
            content_hash="content-crawl-error-api-001",
            title=notice.title,
            notice_type=notice.notice_type,
            issuer=notice.issuer,
            region=notice.region,
            published_at=notice.published_at,
            deadline_at=notice.deadline_at,
            budget_amount=notice.budget_amount,
            budget_currency="CNY",
            structured_data={"scope": "crawl-error-api"},
            change_summary=None,
        )
        session.add(version)
        notice.current_version_id = version.id

        error_1 = CrawlError(
            id=501,
            source_site_id=source_anhui.id,
            crawl_job_id=job_1.id,
            raw_document_id=raw_doc.id,
            stage="parse",
            url="https://ggzy.ah.gov.cn/notice/crawl-error-api",
            error_type="ParserError",
            error_message="parse failed",
            traceback="Traceback (most recent call last): parser",
            retryable=False,
            occurred_at=now - timedelta(hours=2),
            resolved=False,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
        )
        error_2 = CrawlError(
            id=502,
            source_site_id=source_anhui.id,
            crawl_job_id=job_2.id,
            raw_document_id=None,
            stage="fetch",
            url="https://ggzy.ah.gov.cn/list?page=2",
            error_type="FetchTimeout",
            error_message="request timeout",
            traceback=None,
            retryable=True,
            occurred_at=now - timedelta(hours=1),
            resolved=False,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )
        error_3 = CrawlError(
            id=503,
            source_site_id=source_example.id,
            crawl_job_id=job_3.id,
            raw_document_id=None,
            stage="persist",
            url="https://example.com/notices/503",
            error_type="PersistConflict",
            error_message="upsert conflict",
            traceback="Traceback (most recent call last): persist",
            retryable=False,
            occurred_at=now - timedelta(minutes=30),
            resolved=False,
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
        )
        session.add_all([error_1, error_2, error_3])

        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'crawl_error_api.db'}"
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


def test_crawl_error_list_api_supports_filters_sort_and_pagination(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/crawl-errors", params={"limit": 10, "offset": 0})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 3
        assert [item["id"] for item in payload["items"]] == [503, 502, 501]

        by_source = client.get("/crawl-errors", params={"source_code": "anhui_ggzy_zfcg"})
        assert by_source.status_code == 200
        assert by_source.json()["total"] == 2
        assert [item["id"] for item in by_source.json()["items"]] == [502, 501]

        by_stage = client.get("/crawl-errors", params={"stage": "parse"})
        assert by_stage.status_code == 200
        assert by_stage.json()["total"] == 1
        assert by_stage.json()["items"][0]["id"] == 501

        by_job = client.get("/crawl-errors", params={"crawl_job_id": 702})
        assert by_job.status_code == 200
        assert by_job.json()["total"] == 1
        assert by_job.json()["items"][0]["id"] == 502

        by_type = client.get("/crawl-errors", params={"error_type": "PersistConflict"})
        assert by_type.status_code == 200
        assert by_type.json()["total"] == 1
        assert by_type.json()["items"][0]["id"] == 503

        paged = client.get("/crawl-errors", params={"limit": 2, "offset": 1})
        assert paged.status_code == 200
        assert paged.json()["total"] == 3
        assert [item["id"] for item in paged.json()["items"]] == [502, 501]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_error_detail_api_returns_main_fields_and_relations(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/crawl-errors/501")
        assert response.status_code == 200
        payload = response.json()

        assert payload["id"] == 501
        assert payload["source_code"] == "anhui_ggzy_zfcg"
        assert payload["crawl_job_id"] == 701
        assert payload["stage"] == "parse"
        assert payload["error_type"] == "ParserError"
        assert payload["message"] == "parse failed"
        assert payload["detail"] == "parse failed"
        assert payload["url"] == "https://ggzy.ah.gov.cn/notice/crawl-error-api"
        assert "Traceback" in payload["traceback"]

        assert payload["raw_document"] is not None
        assert payload["raw_document"]["id"] == 401
        assert payload["raw_document"]["document_type"] == "html"
        assert payload["raw_document"]["storage_uri"] == "file:///tmp/raw/crawl-error-api-001.html"

        assert payload["notice"] is not None
        assert payload["notice"]["id"] == 101
        assert payload["notice"]["source_code"] == "anhui_ggzy_zfcg"
        assert payload["notice"]["current_version_id"] == 201

        assert payload["notice_version"] is not None
        assert payload["notice_version"]["id"] == 201
        assert payload["notice_version"]["notice_id"] == 101
        assert payload["notice_version"]["version_no"] == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_crawl_error_detail_api_returns_404_when_not_found(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/crawl-errors/999999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
