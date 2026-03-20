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
from app.models import NoticeVersion, RawDocument, SourceSite, TenderNotice


def _seed_data(session_factory: sessionmaker) -> None:
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        source = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="raw document api test",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        source_other = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="raw document api test (other)",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        session.add_all([source, source_other])

        notice = TenderNotice(
            id=101,
            source_site_id=source.id,
            external_id="AH-RAW-001",
            project_code="RAW-001",
            dedup_hash="dedup-raw-001",
            title="低压透明化原文查看测试公告",
            notice_type="announcement",
            issuer="安徽电力公司",
            region="合肥",
            published_at=now - timedelta(days=2),
            deadline_at=now + timedelta(days=7),
            budget_amount=Decimal("100000.00"),
            budget_currency="CNY",
            summary="raw document test",
            first_published_at=now - timedelta(days=2),
            latest_published_at=now - timedelta(days=2),
            current_version_id=None,
        )
        session.add(notice)

        raw_linked = RawDocument(
            id=401,
            source_site_id=source.id,
            crawl_job_id=None,
            url="https://ggzy.ah.gov.cn/notice/raw-001",
            normalized_url="https://ggzy.ah.gov.cn/notice/raw-001",
            url_hash="raw-api-001",
            content_hash="content-raw-api-001",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="低压透明化原文",
            fetched_at=now - timedelta(days=2),
            storage_uri="file:///tmp/raw/raw-api-001.html",
            content_length=1234,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "api"},
        )
        raw_orphan = RawDocument(
            id=402,
            source_site_id=source.id,
            crawl_job_id=None,
            url="https://ggzy.ah.gov.cn/notice/raw-002",
            normalized_url="https://ggzy.ah.gov.cn/notice/raw-002",
            url_hash="raw-api-002",
            content_hash="content-raw-api-002",
            document_type="pdf",
            http_status=200,
            mime_type="application/pdf",
            charset=None,
            title="无关联原文",
            fetched_at=now - timedelta(days=1),
            storage_uri="https://cdn.example.com/raw/raw-api-002.pdf",
            content_length=5678,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "api"},
        )
        raw_with_job = RawDocument(
            id=403,
            source_site_id=source.id,
            crawl_job_id=700,
            url="https://ggzy.ah.gov.cn/notice/raw-003",
            normalized_url="https://ggzy.ah.gov.cn/notice/raw-003",
            url_hash="raw-api-003",
            content_hash="content-raw-api-003",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="任务归档原文",
            fetched_at=now - timedelta(hours=10),
            storage_uri="file:///tmp/raw/raw-api-003.html",
            content_length=1888,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "api"},
        )
        raw_other_source = RawDocument(
            id=404,
            source_site_id=source_other.id,
            crawl_job_id=701,
            url="https://example.com/notice/raw-004",
            normalized_url="https://example.com/notice/raw-004",
            url_hash="raw-api-004",
            content_hash="content-raw-api-004",
            document_type="json",
            http_status=200,
            mime_type="application/json",
            charset="utf-8",
            title="外部来源原文",
            fetched_at=now - timedelta(hours=3),
            storage_uri="file:///tmp/raw/raw-api-004.json",
            content_length=900,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "api"},
        )
        session.add_all([raw_linked, raw_orphan, raw_with_job, raw_other_source])

        version = NoticeVersion(
            id=201,
            notice_id=notice.id,
            raw_document_id=raw_linked.id,
            version_no=1,
            is_current=True,
            content_hash="content-raw-api-001",
            title=notice.title,
            notice_type=notice.notice_type,
            issuer=notice.issuer,
            region=notice.region,
            published_at=notice.published_at,
            deadline_at=notice.deadline_at,
            budget_amount=notice.budget_amount,
            budget_currency="CNY",
            structured_data={"scope": "api"},
            change_summary=None,
        )
        session.add(version)
        notice.current_version_id = version.id

        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'raw_document_api.db'}"
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


def test_raw_document_detail_api_returns_core_fields_and_notice_summaries(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/raw-documents/401")
        assert response.status_code == 200

        payload = response.json()
        assert payload["id"] == 401
        assert payload["source_code"] == "anhui_ggzy_zfcg"
        assert payload["crawl_job_id"] is None
        assert payload["url"] == "https://ggzy.ah.gov.cn/notice/raw-001"
        assert payload["normalized_url"] == "https://ggzy.ah.gov.cn/notice/raw-001"
        assert payload["document_type"] == "html"
        assert payload["storage_uri"] == "file:///tmp/raw/raw-api-001.html"
        assert payload["mime_type"] == "text/html"
        assert payload["title"] == "低压透明化原文"
        assert payload["content_hash"] == "content-raw-api-001"

        assert payload["notice_version"] is not None
        assert payload["notice_version"]["id"] == 201
        assert payload["notice_version"]["notice_id"] == 101
        assert payload["notice_version"]["version_no"] == 1
        assert payload["notice_version"]["is_current"] is True
        assert payload["notice_version"]["notice_type"] == "announcement"

        assert payload["tender_notice"] is not None
        assert payload["tender_notice"]["id"] == 101
        assert payload["tender_notice"]["source_code"] == "anhui_ggzy_zfcg"
        assert payload["tender_notice"]["title"] == "低压透明化原文查看测试公告"
        assert payload["tender_notice"]["notice_type"] == "announcement"
        assert payload["tender_notice"]["current_version_id"] == 201
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_raw_document_detail_api_returns_null_summaries_when_unlinked(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/raw-documents/402")
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == 402
        assert payload["notice_version"] is None
        assert payload["tender_notice"] is None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_raw_document_detail_api_returns_404_when_not_found(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/raw-documents/999999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_raw_document_list_api_supports_filters_sort_and_pagination(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/raw-documents", params={"limit": 10, "offset": 0})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 4
        assert [item["id"] for item in payload["items"]] == [404, 403, 402, 401]

        sample = payload["items"][0]
        assert sample["source_code"] == "example_source"
        assert sample["document_type"] == "json"
        assert sample["url"] == "https://example.com/notice/raw-004"
        assert sample["normalized_url"] == "https://example.com/notice/raw-004"
        assert sample["content_hash"] == "content-raw-api-004"

        by_source = client.get("/raw-documents", params={"source_code": "anhui_ggzy_zfcg"})
        assert by_source.status_code == 200
        assert by_source.json()["total"] == 3
        assert [item["id"] for item in by_source.json()["items"]] == [403, 402, 401]

        by_type = client.get("/raw-documents", params={"document_type": "html"})
        assert by_type.status_code == 200
        assert by_type.json()["total"] == 2
        assert [item["id"] for item in by_type.json()["items"]] == [403, 401]

        by_job = client.get("/raw-documents", params={"crawl_job_id": 700})
        assert by_job.status_code == 200
        assert by_job.json()["total"] == 1
        assert by_job.json()["items"][0]["id"] == 403

        by_hash = client.get("/raw-documents", params={"content_hash": "content-raw-api-001"})
        assert by_hash.status_code == 200
        assert by_hash.json()["total"] == 1
        assert by_hash.json()["items"][0]["id"] == 401

        paged = client.get("/raw-documents", params={"limit": 2, "offset": 1})
        assert paged.status_code == 200
        assert paged.json()["total"] == 4
        assert [item["id"] for item in paged.json()["items"]] == [403, 402]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
