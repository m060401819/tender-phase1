from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services import CrawlJobService
from tender_crawler.writers.sqlalchemy_writer import (
    SqlAlchemyNoticeWriter,
    SqlAlchemyRawDocumentWriter,
    SqlAlchemyWriterContext,
)


def test_phase3_source_duplicate_suppression_reflected_in_notices_and_crawl_job_stats(tmp_path: Path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'phase3_source_duplicate_integration.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    context = SqlAlchemyWriterContext(database_url=db_url)
    raw_writer = SqlAlchemyRawDocumentWriter(context=context)
    notice_writer = SqlAlchemyNoticeWriter(context=context)
    job_service = CrawlJobService(session_factory=session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        job = job_service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual", triggered_by="pytest")
        job_service.start_job(job.id)

        raw_writer.write_raw_document(
            {
                "source_code": "anhui_ggzy_zfcg",
                "source_site_name": "安徽省公共资源交易监管网",
                "source_site_url": "https://ggzy.ah.gov.cn",
                "crawl_job_id": job.id,
                "url": "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
                "raw_body": "<html>list</html>",
                "document_type": "html",
                "fetched_at": "2026-03-20T00:00:00+00:00",
                "storage_uri": "raw/list.html",
                "http_status": 200,
                "extra_meta": {
                    "role": "list",
                    "page_item_count": 3,
                    "new_unique_item_count": 2,
                    "page_source_duplicates_skipped": 1,
                },
            }
        )
        raw_writer.write_raw_document(
            {
                "source_code": "anhui_ggzy_zfcg",
                "source_site_name": "安徽省公共资源交易监管网",
                "source_site_url": "https://ggzy.ah.gov.cn",
                "crawl_job_id": job.id,
                "url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=a",
                "raw_body": "<html>detail-a</html>",
                "document_type": "html",
                "fetched_at": "2026-03-20T00:01:00+00:00",
                "storage_uri": "raw/detail-a.html",
                "http_status": 200,
                "extra_meta": {"role": "detail"},
            }
        )
        raw_writer.write_raw_document(
            {
                "source_code": "anhui_ggzy_zfcg",
                "source_site_name": "安徽省公共资源交易监管网",
                "source_site_url": "https://ggzy.ah.gov.cn",
                "crawl_job_id": job.id,
                "url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=b",
                "raw_body": "<html>detail-b</html>",
                "document_type": "html",
                "fetched_at": "2026-03-20T00:02:00+00:00",
                "storage_uri": "raw/detail-b.html",
                "http_status": 200,
                "extra_meta": {"role": "detail"},
            }
        )

        base_notice = {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "crawl_job_id": job.id,
            "title": "低压透明化改造项目公告",
            "notice_type": "announcement",
            "published_at": "2026-03-20T00:00:00+00:00",
        }
        base_version = {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "crawl_job_id": job.id,
            "title": "低压透明化改造项目公告",
            "notice_type": "announcement",
            "published_at": "2026-03-20T00:00:00+00:00",
            "version_no": 1,
            "is_current": True,
        }

        notice_writer.write_notice(
            {
                **base_notice,
                "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=a",
                "source_duplicate_key": "src-dup-key-a",
                "raw_content_hash": "hash-a-v1",
                "content_text": "正文 a v1",
            }
        )
        notice_writer.write_notice_version(
            {
                **base_version,
                "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=a",
                "source_duplicate_key": "src-dup-key-a",
                "content_hash": "hash-a-v1",
                "content_text": "正文 a v1",
            }
        )

        # 源站重复：同 source_duplicate_key + 同内容，应被抑制
        notice_writer.write_notice(
            {
                **base_notice,
                "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=a",
                "source_duplicate_key": "src-dup-key-a",
                "raw_content_hash": "hash-a-v1",
                "content_text": "正文 a v1",
            }
        )
        notice_writer.write_notice_version(
            {
                **base_version,
                "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=a",
                "source_duplicate_key": "src-dup-key-a",
                "content_hash": "hash-a-v1",
                "content_text": "正文 a v1",
            }
        )

        # 正常不同公告
        notice_writer.write_notice(
            {
                **base_notice,
                "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=b",
                "title": "负荷管理平台采购公告",
                "source_duplicate_key": "src-dup-key-b",
                "raw_content_hash": "hash-b-v1",
                "content_text": "正文 b v1",
            }
        )
        notice_writer.write_notice_version(
            {
                **base_version,
                "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=b",
                "title": "负荷管理平台采购公告",
                "source_duplicate_key": "src-dup-key-b",
                "content_hash": "hash-b-v1",
                "content_text": "正文 b v1",
            }
        )

        finished = job_service.finish_job(job.id)
        assert finished is not None

        job_resp = client.get(f"/crawl-jobs/{job.id}")
        assert job_resp.status_code == 200
        job_payload = job_resp.json()
        assert job_payload["list_items_seen"] == 3
        assert job_payload["list_items_unique"] == 2
        assert job_payload["list_items_source_duplicates_skipped"] == 1
        assert job_payload["detail_pages_fetched"] == 2
        assert job_payload["source_duplicates_suppressed"] == 1

        notices_resp = client.get(
            "/notices",
            params={"source_code": "anhui_ggzy_zfcg", "dedup": "false", "limit": 20, "offset": 0},
        )
        assert notices_resp.status_code == 200
        notices_payload = notices_resp.json()
        assert notices_payload["total"] == 2

        admin_job_resp = client.get(f"/admin/crawl-jobs/{job.id}")
        assert admin_job_resp.status_code == 200
        assert "list_items_source_duplicates_skipped" in admin_job_resp.text
        assert "source_duplicates_suppressed" in admin_job_resp.text
    finally:
        app.dependency_overrides.clear()
        context.close()
        engine.dispose()
