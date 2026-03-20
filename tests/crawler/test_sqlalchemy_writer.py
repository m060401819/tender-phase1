from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, func, select

import app.models  # noqa: F401
from app.db.base import Base
from app.models import CrawlError, NoticeVersion, RawDocument, SourceSite, TenderAttachment, TenderNotice
from app.services import CrawlJobService
from tender_crawler.utils import normalize_url, sha256_text
from tender_crawler.writers.sqlalchemy_writer import (
    SqlAlchemyErrorWriter,
    SqlAlchemyNoticeWriter,
    SqlAlchemyRawDocumentWriter,
    SqlAlchemyWriterContext,
)


def _make_context(db_path: Path) -> SqlAlchemyWriterContext:
    database_url = f"sqlite+pysqlite:///{db_path}"
    bootstrap_engine = create_engine(database_url)
    Base.metadata.create_all(bootstrap_engine)
    bootstrap_engine.dispose()
    return SqlAlchemyWriterContext(database_url=database_url)


def test_sqlalchemy_writers_persist_phase1_entities(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "crawler_writer.db")
    raw_writer = SqlAlchemyRawDocumentWriter(context=context)
    notice_writer = SqlAlchemyNoticeWriter(context=context)
    error_writer = SqlAlchemyErrorWriter(context=context)
    raw_detail_url = "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123&subType=bulletin"
    raw_url_hash = sha256_text(normalize_url(raw_detail_url))
    attachment_url = "https://ggzy.ah.gov.cn/download/spec.pdf"
    attachment_url_hash = sha256_text(normalize_url(attachment_url))

    raw_writer.write_raw_document(
        {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "crawl_job_id": None,
            "url": raw_detail_url,
            "normalized_url": raw_detail_url,
            "url_hash": "raw-url-hash-1",
            "content_hash": "raw-content-hash-1",
            "document_type": "html",
            "http_status": 200,
            "mime_type": "text/html",
            "charset": "utf-8",
            "title": "测试项目采购公告",
            "fetched_at": "2026-03-19T08:00:00+00:00",
            "storage_uri": "data/raw/anhui/abc123.html",
            "content_length": 1234,
            "extra_meta": {"role": "detail_sub_bulletin"},
        }
    )

    notice_writer.write_notice(
        {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "external_id": "abc123",
            "project_code": "HF-2026-001",
            "dedup_hash": "notice-dedup-hash-1",
            "title": "测试项目采购公告",
            "notice_type": "announcement",
            "issuer": "合肥市测试局",
            "region": "安徽省合肥市",
            "published_at": "2026-03-10T01:30:00+00:00",
            "deadline_at": "2026-03-20T02:00:00+00:00",
            "budget_amount": "1635000",
            "budget_currency": "CNY",
            "summary": "测试摘要",
            "list_page_url": "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
            "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
            "content_text": "正文内容",
        }
    )

    notice_writer.write_notice_version(
        {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "notice_dedup_hash": "notice-dedup-hash-1",
            "notice_external_id": "abc123",
            "version_no": 1,
            "is_current": True,
            "content_hash": "notice-content-hash-1",
            "title": "测试项目采购公告",
            "notice_type": "announcement",
            "issuer": "合肥市测试局",
            "region": "安徽省合肥市",
            "published_at": "2026-03-10T01:30:00+00:00",
            "deadline_at": "2026-03-20T02:00:00+00:00",
            "budget_amount": "1635000",
            "budget_currency": "CNY",
            "structured_data": {"foo": "bar"},
            "change_summary": None,
            "raw_document_url_hash": raw_url_hash,
            "list_page_url": "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
            "detail_page_url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
            "content_text": "正文内容",
        }
    )

    notice_writer.write_attachment(
        {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "notice_dedup_hash": "notice-dedup-hash-1",
            "notice_external_id": "abc123",
            "notice_version_no": 1,
            "file_name": "spec.pdf",
            "attachment_type": "notice_file",
            "file_url": attachment_url,
            "url_hash": "attachment-url-hash-1",
            "file_hash": None,
            "storage_uri": None,
            "mime_type": "application/pdf",
            "file_ext": "pdf",
            "file_size_bytes": None,
            "published_at": "2026-03-10T01:30:00+00:00",
        }
    )

    error_writer.write_error(
        {
            "source_code": "anhui_ggzy_zfcg",
            "source_site_name": "安徽省公共资源交易监管网",
            "source_site_url": "https://ggzy.ah.gov.cn",
            "crawl_job_id": None,
            "stage": "parse",
            "url": "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
            "error_type": "UnitTestError",
            "error_message": "just for test",
            "traceback": "",
            "retryable": False,
            "occurred_at": "2026-03-19T08:01:00+00:00",
        }
    )

    with context.session() as session:
        assert session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg")) is not None

        raw_document = session.scalar(select(RawDocument).where(RawDocument.url_hash == raw_url_hash))
        assert raw_document is not None

        notice = session.scalar(select(TenderNotice).where(TenderNotice.external_id == "abc123"))
        assert notice is not None
        assert notice.external_id == "abc123"

        version = session.scalar(select(NoticeVersion).where(NoticeVersion.content_hash == "notice-content-hash-1"))
        assert version is not None
        assert version.raw_document_id == raw_document.id
        assert notice.current_version_id == version.id

        attachment = session.scalar(select(TenderAttachment).where(TenderAttachment.url_hash == attachment_url_hash))
        assert attachment is not None
        assert attachment.notice_id == notice.id
        assert attachment.notice_version_id == version.id

        crawl_error = session.scalar(select(CrawlError).where(CrawlError.error_type == "UnitTestError"))
        assert crawl_error is not None
        assert crawl_error.source_site_id == notice.source_site_id

    context.close()


def test_raw_document_url_hash_dedup_by_normalized_url(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "raw_url_dedup.db")
    writer = SqlAlchemyRawDocumentWriter(context=context)

    writer.write_raw_document(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "url": "https://example.com/a?b=2&a=1#frag",
            "normalized_url": None,
            "url_hash": None,
            "content_hash": None,
            "document_type": "html",
            "fetched_at": "2026-03-19T08:00:00+00:00",
            "storage_uri": "raw/1.html",
            "raw_body": "body-v1",
            "http_status": 200,
        }
    )
    writer.write_raw_document(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "url": "https://example.com/a?a=1&b=2",
            "normalized_url": None,
            "url_hash": None,
            "content_hash": None,
            "document_type": "html",
            "fetched_at": "2026-03-19T08:05:00+00:00",
            "storage_uri": "raw/2.html",
            "raw_body": "body-v2",
            "http_status": 200,
        }
    )

    with context.session() as session:
        records = session.scalars(select(RawDocument).order_by(RawDocument.id)).all()
        assert len(records) == 1
        assert records[0].normalized_url == "https://example.com/a?a=1&b=2"
        assert records[0].url_hash is not None
        assert records[0].is_duplicate_url is True

    context.close()


def test_raw_document_content_hash_dedup_marks_duplicate(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "raw_content_dedup.db")
    writer = SqlAlchemyRawDocumentWriter(context=context)

    payload_base = {
        "source_code": "src",
        "source_site_name": "Source",
        "source_site_url": "https://example.com",
        "document_type": "html",
        "fetched_at": "2026-03-19T08:00:00+00:00",
        "http_status": 200,
    }
    writer.write_raw_document(
        {
            **payload_base,
            "url": "https://example.com/a?id=1",
            "storage_uri": "raw/a1.html",
            "raw_body": "same-content",
        }
    )
    writer.write_raw_document(
        {
            **payload_base,
            "url": "https://example.com/a?id=2",
            "storage_uri": "raw/a2.html",
            "raw_body": "same-content",
        }
    )

    with context.session() as session:
        records = session.scalars(select(RawDocument).order_by(RawDocument.id)).all()
        assert len(records) == 2
        assert records[0].is_duplicate_content is False
        assert records[1].is_duplicate_content is True

    context.close()


def test_notice_versioning_dedup_and_increment(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "notice_versioning.db")
    notice_writer = SqlAlchemyNoticeWriter(context=context)

    base_notice = {
        "source_code": "src",
        "source_site_name": "Source",
        "source_site_url": "https://example.com",
        "external_id": "N-1001",
        "detail_page_url": "https://example.com/notice/detail?id=1001",
        "title": "公告A",
        "notice_type": "announcement",
        "issuer": "采购人A",
        "region": "安徽",
        "published_at": "2026-03-10T01:30:00+00:00",
        "budget_amount": "1000",
    }
    notice_writer.write_notice(base_notice)

    version_v1 = {
        "source_code": "src",
        "source_site_name": "Source",
        "source_site_url": "https://example.com",
        "notice_external_id": "N-1001",
        "detail_page_url": "https://example.com/notice/detail?id=1001",
        "version_no": 1,
        "is_current": True,
        "title": "公告A",
        "notice_type": "announcement",
        "issuer": "采购人A",
        "region": "安徽",
        "published_at": "2026-03-10T01:30:00+00:00",
        "content_text": "正文v1",
    }
    notice_writer.write_notice_version(version_v1)
    notice_writer.write_notice_version(version_v1)

    version_v2 = {
        **version_v1,
        "title": "公告A（更新）",
        "notice_type": "unknown_type",
        "content_text": "正文v2",
    }
    notice_writer.write_notice_version(version_v2)

    with context.session() as session:
        notice_count = session.scalar(select(func.count()).select_from(TenderNotice))
        version_count = session.scalar(select(func.count()).select_from(NoticeVersion))
        assert notice_count == 1
        assert version_count == 2

        notice = session.scalar(select(TenderNotice))
        assert notice is not None
        assert notice.title == "公告A（更新）"
        assert notice.notice_type == "announcement"
        assert notice.current_version_id is not None

        versions = session.scalars(
            select(NoticeVersion)
            .where(NoticeVersion.notice_id == notice.id)
            .order_by(NoticeVersion.version_no)
        ).all()
        assert [v.version_no for v in versions] == [1, 2]
        assert versions[0].is_current is False
        assert versions[1].is_current is True
        assert versions[0].content_hash != versions[1].content_hash

    context.close()


def test_notice_merge_strategy_by_detail_url_without_external_id(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "notice_merge.db")
    notice_writer = SqlAlchemyNoticeWriter(context=context)

    notice_writer.write_notice(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "external_id": None,
            "detail_page_url": "https://example.com/notice/detail?id=2001",
            "title": "第一次标题",
            "notice_type": "announcement",
        }
    )
    notice_writer.write_notice(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "external_id": None,
            "detail_page_url": "https://example.com/notice/detail?id=2001",
            "title": "第二次标题",
            "notice_type": "announcement",
        }
    )

    with context.session() as session:
        notice_count = session.scalar(select(func.count()).select_from(TenderNotice))
        assert notice_count == 1
        notice = session.scalar(select(TenderNotice))
        assert notice is not None
        assert notice.title == "第二次标题"
        assert notice.dedup_hash is not None

    context.close()


def test_attachment_url_normalization_and_dedup(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "attachment_dedup.db")
    notice_writer = SqlAlchemyNoticeWriter(context=context)

    notice_writer.write_notice(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "external_id": "N-attach-1",
            "detail_page_url": "https://example.com/notice/detail?id=3001",
            "title": "附件测试公告",
            "notice_type": "announcement",
        }
    )
    notice_writer.write_notice_version(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "notice_external_id": "N-attach-1",
            "detail_page_url": "https://example.com/notice/detail?id=3001",
            "title": "附件测试公告",
            "notice_type": "announcement",
            "content_text": "正文",
            "version_no": 1,
            "is_current": True,
        }
    )

    notice_writer.write_attachment(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "notice_external_id": "N-attach-1",
            "detail_page_url": "https://example.com/notice/detail?id=3001",
            "file_name": "spec.pdf",
            "attachment_type": "notice_file",
            "file_url": "https://example.com/files/spec.pdf?b=2&a=1#frag",
            "url_hash": None,
            "mime_type": None,
            "file_size_bytes": 12,
        }
    )
    notice_writer.write_attachment(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "notice_external_id": "N-attach-1",
            "detail_page_url": "https://example.com/notice/detail?id=3001",
            "file_name": "spec.pdf",
            "attachment_type": "notice_file",
            "file_url": "https://example.com/files/spec.pdf?a=1&b=2",
            "url_hash": None,
            "mime_type": None,
            "file_size_bytes": 13,
        }
    )

    with context.session() as session:
        attachments = session.scalars(select(TenderAttachment)).all()
        assert len(attachments) == 1
        assert attachments[0].file_url == "https://example.com/files/spec.pdf?a=1&b=2"
        assert attachments[0].url_hash == sha256_text("https://example.com/files/spec.pdf?a=1&b=2")
        assert attachments[0].file_size_bytes == 13

    context.close()


def test_attachment_uses_current_notice_version_when_version_no_missing(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "attachment_current_version.db")
    notice_writer = SqlAlchemyNoticeWriter(context=context)

    base_notice = {
        "source_code": "src",
        "source_site_name": "Source",
        "source_site_url": "https://example.com",
        "external_id": "N-attach-2",
        "detail_page_url": "https://example.com/notice/detail?id=4001",
        "title": "版本附件测试公告",
        "notice_type": "announcement",
    }
    notice_writer.write_notice(base_notice)
    notice_writer.write_notice_version(
        {
            **base_notice,
            "notice_external_id": "N-attach-2",
            "content_text": "正文v1",
            "version_no": 1,
            "is_current": True,
        }
    )
    notice_writer.write_notice_version(
        {
            **base_notice,
            "notice_external_id": "N-attach-2",
            "title": "版本附件测试公告（更新）",
            "content_text": "正文v2",
            "version_no": 1,
            "is_current": True,
        }
    )

    notice_writer.write_attachment(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "notice_external_id": "N-attach-2",
            "detail_page_url": "https://example.com/notice/detail?id=4001",
            "file_name": "attachment.zip",
            "attachment_type": "notice_file",
            "file_url": "https://example.com/files/attachment.zip",
            "url_hash": None,
            "notice_version_no": None,
        }
    )

    with context.session() as session:
        notice = session.scalar(select(TenderNotice).where(TenderNotice.external_id == "N-attach-2"))
        assert notice is not None
        attachment = session.scalar(select(TenderAttachment).where(TenderAttachment.notice_id == notice.id))
        assert attachment is not None
        assert attachment.notice_version_id == notice.current_version_id

    context.close()


def test_attachment_links_raw_document_by_url_hash(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "attachment_raw_document.db")
    raw_writer = SqlAlchemyRawDocumentWriter(context=context)
    notice_writer = SqlAlchemyNoticeWriter(context=context)

    attachment_url = "https://example.com/files/spec.docx"
    attachment_url_hash = sha256_text(normalize_url(attachment_url))

    raw_writer.write_raw_document(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "url": attachment_url,
            "normalized_url": attachment_url,
            "url_hash": attachment_url_hash,
            "content_hash": "file-content-hash",
            "document_type": "pdf",
            "fetched_at": "2026-03-19T08:00:00+00:00",
            "storage_uri": "data/attachments/src/spec.docx",
            "raw_body": "",
            "http_status": 200,
        }
    )
    notice_writer.write_notice(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "external_id": "N-attach-3",
            "detail_page_url": "https://example.com/notice/detail?id=5001",
            "title": "附件原文关联公告",
            "notice_type": "announcement",
        }
    )
    notice_writer.write_notice_version(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "notice_external_id": "N-attach-3",
            "detail_page_url": "https://example.com/notice/detail?id=5001",
            "title": "附件原文关联公告",
            "notice_type": "announcement",
            "content_text": "正文",
            "version_no": 1,
            "is_current": True,
        }
    )
    notice_writer.write_attachment(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "notice_external_id": "N-attach-3",
            "detail_page_url": "https://example.com/notice/detail?id=5001",
            "file_name": "spec.docx",
            "attachment_type": "notice_file",
            "file_url": attachment_url,
            "url_hash": attachment_url_hash,
        }
    )

    with context.session() as session:
        raw_document = session.scalar(select(RawDocument).where(RawDocument.url_hash == attachment_url_hash))
        assert raw_document is not None
        attachment = session.scalar(select(TenderAttachment).where(TenderAttachment.url_hash == attachment_url_hash))
        assert attachment is not None
        assert attachment.raw_document_id == raw_document.id

    context.close()


def test_sqlalchemy_writer_updates_crawl_job_metrics(tmp_path: Path) -> None:
    context = _make_context(tmp_path / "crawl_job_metrics.db")
    service = CrawlJobService(session_factory=context.session_factory)
    raw_writer = SqlAlchemyRawDocumentWriter(context=context)
    notice_writer = SqlAlchemyNoticeWriter(context=context)
    error_writer = SqlAlchemyErrorWriter(context=context)

    job = service.create_job(source_code="src", job_type="manual", triggered_by="pytest")
    running = service.start_job(job.id)
    assert running is not None
    assert running.status == "running"

    raw_writer.write_raw_document(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "crawl_job_id": job.id,
            "url": "https://example.com/a?b=2&a=1#frag",
            "content_hash": None,
            "document_type": "html",
            "fetched_at": "2026-03-19T08:00:00+00:00",
            "storage_uri": "raw/1.html",
            "raw_body": "dup-body",
            "http_status": 200,
        }
    )
    raw_writer.write_raw_document(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "crawl_job_id": job.id,
            "url": "https://example.com/a?a=1&b=2",
            "content_hash": None,
            "document_type": "html",
            "fetched_at": "2026-03-19T08:05:00+00:00",
            "storage_uri": "raw/2.html",
            "raw_body": "dup-body",
            "http_status": 200,
        }
    )

    notice_writer.write_notice(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "crawl_job_id": job.id,
            "detail_page_url": "https://example.com/notice/detail?id=9001",
            "title": "统计回传公告",
            "notice_type": "announcement",
        }
    )
    notice_writer.write_notice(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "crawl_job_id": job.id,
            "detail_page_url": "https://example.com/notice/detail?id=9001",
            "title": "统计回传公告（更新）",
            "notice_type": "announcement",
        }
    )

    error_writer.write_error(
        {
            "source_code": "src",
            "source_site_name": "Source",
            "source_site_url": "https://example.com",
            "crawl_job_id": job.id,
            "stage": "parse",
            "url": "https://example.com/notice/detail?id=9001",
            "error_type": "UnitTestMetricsError",
            "error_message": "test",
            "traceback": "",
            "retryable": False,
            "occurred_at": "2026-03-19T08:06:00+00:00",
        }
    )

    finished = service.finish_job(job.id)
    assert finished is not None
    assert finished.status == "partial"
    assert finished.pages_fetched == 2
    assert finished.documents_saved == 2
    assert finished.notices_upserted == 2
    assert finished.error_count == 1
    assert finished.deduplicated_count >= 2

    context.close()
