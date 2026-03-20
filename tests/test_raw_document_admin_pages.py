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


def _seed_data(session_factory: sessionmaker, *, storage_file: Path) -> None:
    now = datetime.now(timezone.utc)

    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text("<html><body>raw-local-401</body></html>", encoding="utf-8")

    with session_factory() as session:
        source = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="raw document admin test",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        source_other = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="raw document admin test (other)",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        session.add_all([source, source_other])

        notice = TenderNotice(
            id=101,
            source_site_id=source.id,
            external_id="AH-ADMIN-RAW-001",
            project_code="ADMIN-RAW-001",
            dedup_hash="dedup-admin-raw-001",
            title="原始文档后台查看测试公告",
            notice_type="announcement",
            issuer="安徽电力公司",
            region="合肥",
            published_at=now - timedelta(days=1),
            deadline_at=now + timedelta(days=6),
            budget_amount=Decimal("123456.00"),
            budget_currency="CNY",
            summary="raw admin test",
            first_published_at=now - timedelta(days=1),
            latest_published_at=now - timedelta(days=1),
            current_version_id=None,
        )
        session.add(notice)

        raw_local = RawDocument(
            id=401,
            source_site_id=source.id,
            crawl_job_id=None,
            url="https://ggzy.ah.gov.cn/notice/admin-raw-001",
            normalized_url="https://ggzy.ah.gov.cn/notice/admin-raw-001",
            url_hash="raw-admin-001",
            content_hash="content-raw-admin-001",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="可下载原文",
            fetched_at=now - timedelta(days=1),
            storage_uri=storage_file.resolve().as_uri(),
            content_length=222,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "admin"},
        )
        raw_remote = RawDocument(
            id=402,
            source_site_id=source.id,
            crawl_job_id=None,
            url="https://ggzy.ah.gov.cn/notice/admin-raw-002",
            normalized_url="https://ggzy.ah.gov.cn/notice/admin-raw-002",
            url_hash="raw-admin-002",
            content_hash="content-raw-admin-002",
            document_type="pdf",
            http_status=200,
            mime_type="application/pdf",
            charset=None,
            title="不可本地访问原文",
            fetched_at=now,
            storage_uri="https://cdn.example.com/raw/raw-admin-002.pdf",
            content_length=333,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "admin"},
        )
        raw_with_job = RawDocument(
            id=403,
            source_site_id=source.id,
            crawl_job_id=900,
            url="https://ggzy.ah.gov.cn/notice/admin-raw-003",
            normalized_url="https://ggzy.ah.gov.cn/notice/admin-raw-003",
            url_hash="raw-admin-003",
            content_hash="content-raw-admin-003",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="任务原文记录",
            fetched_at=now - timedelta(hours=8),
            storage_uri="file:///tmp/raw/raw-admin-003.html",
            content_length=666,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "admin"},
        )
        raw_other_source = RawDocument(
            id=404,
            source_site_id=source_other.id,
            crawl_job_id=901,
            url="https://example.com/notice/admin-raw-004",
            normalized_url="https://example.com/notice/admin-raw-004",
            url_hash="raw-admin-004",
            content_hash="content-raw-admin-004",
            document_type="json",
            http_status=200,
            mime_type="application/json",
            charset="utf-8",
            title="外部来源原文",
            fetched_at=now - timedelta(hours=2),
            storage_uri="file:///tmp/raw/raw-admin-004.json",
            content_length=500,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"scope": "admin"},
        )
        session.add_all([raw_local, raw_remote, raw_with_job, raw_other_source])

        version = NoticeVersion(
            id=201,
            notice_id=notice.id,
            raw_document_id=raw_local.id,
            version_no=1,
            is_current=True,
            content_hash="content-raw-admin-001",
            title=notice.title,
            notice_type=notice.notice_type,
            issuer=notice.issuer,
            region=notice.region,
            published_at=notice.published_at,
            deadline_at=notice.deadline_at,
            budget_amount=notice.budget_amount,
            budget_currency="CNY",
            structured_data={"scope": "admin"},
            change_summary=None,
        )
        session.add(version)
        notice.current_version_id = version.id

        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'raw_document_admin_pages.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_data(session_factory, storage_file=tmp_path / "raw" / "admin-raw-001.html")

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, engine


def test_admin_raw_document_detail_page_shows_fields_relations_and_download_link(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/raw-documents/401")
        assert response.status_code == 200
        assert "原始文档详情 #401" in response.text
        assert "source_code" in response.text
        assert "content-raw-admin-001" in response.text
        assert "/admin/raw-documents/401/download" in response.text
        assert "/admin/notices/101" in response.text
        assert "/admin/raw-documents?source_code=anhui_ggzy_zfcg" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_raw_document_detail_page_hides_download_when_storage_not_local(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/raw-documents/402")
        assert response.status_code == 200
        assert "原始文档详情 #402" in response.text
        assert "本地文件不可访问" in response.text
        assert "/admin/raw-documents/402/download" not in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_raw_document_download_endpoint_and_404_cases(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        download = client.get("/admin/raw-documents/401/download")
        assert download.status_code == 200
        assert b"raw-local-401" in download.content

        not_local = client.get("/admin/raw-documents/402/download")
        assert not_local.status_code == 404

        not_found = client.get("/admin/raw-documents/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_raw_document_list_page_supports_filters_pagination_and_detail_links(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/raw-documents")
        assert response.status_code == 200
        assert "原始文档列表" in response.text
        assert "/admin/raw-documents/401" in response.text
        assert "/admin/raw-documents/404" in response.text

        filtered = client.get(
            "/admin/raw-documents",
            params={
                "source_code": "anhui_ggzy_zfcg",
                "document_type": "html",
                "crawl_job_id": 900,
            },
        )
        assert filtered.status_code == 200
        assert "任务原文记录" in filtered.text
        assert "外部来源原文" not in filtered.text

        paged = client.get("/admin/raw-documents", params={"limit": 1, "offset": 1})
        assert paged.status_code == 200
        assert "total=4 | limit=1 | offset=1" in paged.text
        assert "/admin/raw-documents/404" in paged.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_raw_document_list_page_keeps_notice_jump_context(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        notice_page = client.get("/admin/notices/101")
        assert notice_page.status_code == 200
        assert "/admin/raw-documents?source_code=anhui_ggzy_zfcg&from_notice_id=101" in notice_page.text

        from_notice = client.get(
            "/admin/raw-documents",
            params={"source_code": "anhui_ggzy_zfcg", "from_notice_id": 101},
        )
        assert from_notice.status_code == 200
        assert "/admin/notices/101" in from_notice.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
