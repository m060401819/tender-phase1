from __future__ import annotations

import json
from pathlib import Path

from tender_crawler.items import (
    ITEM_TYPE_CRAWL_ERROR,
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_ATTACHMENT,
    ITEM_TYPE_TENDER_NOTICE,
    CrawlErrorItem,
    NoticeVersionItem,
    RawDocumentItem,
    TenderAttachmentItem,
    TenderNoticeItem,
)
from tender_crawler.pipelines import AttachmentArchivePipeline, RawArchivePipeline, WriterDispatchPipeline
from tender_crawler.services import AttachmentArchiveResult, BaseAttachmentArchiver
from tender_crawler.writers.base import (
    BaseErrorWriter,
    BaseNoticeWriter,
    BaseRawDocumentWriter,
    WriterBundle,
)


class _SpiderStub:
    name = "test_spider"


class _RawRecorder(BaseRawDocumentWriter):
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def write_raw_document(self, item: dict) -> None:
        self.payloads.append(item)


class _NoticeRecorder(BaseNoticeWriter):
    def __init__(self) -> None:
        self.notice_payloads: list[dict] = []
        self.version_payloads: list[dict] = []
        self.attachment_payloads: list[dict] = []

    def write_notice(self, item: dict) -> None:
        self.notice_payloads.append(item)

    def write_notice_version(self, item: dict) -> None:
        self.version_payloads.append(item)

    def write_attachment(self, item: dict) -> None:
        self.attachment_payloads.append(item)


class _ErrorRecorder(BaseErrorWriter):
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def write_error(self, item: dict) -> None:
        self.payloads.append(item)


class _AttachmentArchiverStub(BaseAttachmentArchiver):
    def archive(self, item: dict) -> AttachmentArchiveResult:
        _ = item
        return AttachmentArchiveResult(
            storage_uri="/tmp/attachments/spec.pdf",
            file_hash="hash-spec",
            mime_type="application/pdf",
            file_size_bytes=2048,
        )


def test_raw_archive_pipeline_persists_files(tmp_path: Path) -> None:
    pipeline = RawArchivePipeline(base_dir=str(tmp_path / "raw"))
    spider = _SpiderStub()
    item = RawDocumentItem(
        item_type=ITEM_TYPE_RAW_DOCUMENT,
        source_code="example_source",
        crawl_job_id=None,
        url="https://example.com/notices/1",
        normalized_url="https://example.com/notices/1",
        url_hash="abc",
        content_hash="def",
        document_type="html",
        fetched_at="2026-01-01T00:00:00+00:00",
        storage_uri="",
        raw_body="<html>hello</html>",
        http_status=200,
        mime_type="text/html",
        charset="utf-8",
        title="hello",
        content_length=0,
        extra_meta={},
    )

    processed = pipeline.process_item(item, spider)
    storage_uri = processed.get("storage_uri")
    assert storage_uri
    assert Path(storage_uri).exists()

    meta_path = Path(processed["extra_meta"]["archive_meta"])
    assert meta_path.exists()
    loaded = json.loads(meta_path.read_text(encoding="utf-8"))
    assert loaded["item_type"] == ITEM_TYPE_RAW_DOCUMENT


def test_attachment_archive_pipeline_enriches_attachment_metadata() -> None:
    pipeline = AttachmentArchivePipeline(archiver=_AttachmentArchiverStub())
    spider = _SpiderStub()
    item = TenderAttachmentItem(
        item_type=ITEM_TYPE_TENDER_ATTACHMENT,
        source_code="example_source",
        crawl_job_id=None,
        notice_dedup_hash="n1",
        notice_external_id="ext1",
        notice_version_no=1,
        file_name="spec.pdf",
        attachment_type="notice_file",
        file_url="https://example.com/files/spec.pdf",
        url_hash="u1",
        file_hash=None,
        storage_uri=None,
        mime_type=None,
        file_ext="pdf",
        file_size_bytes=None,
        published_at=None,
        downloaded_at=None,
        source_url="https://example.com/detail/1",
    )

    processed = pipeline.process_item(item, spider)
    assert processed["storage_uri"] == "/tmp/attachments/spec.pdf"
    assert processed["file_hash"] == "hash-spec"
    assert processed["mime_type"] == "application/pdf"
    assert processed["file_size_bytes"] == 2048
    assert processed["downloaded_at"] is not None


def test_writer_dispatch_pipeline_routes_by_item_type() -> None:
    raw_writer = _RawRecorder()
    notice_writer = _NoticeRecorder()
    error_writer = _ErrorRecorder()
    bundle = WriterBundle(
        raw_document_writer=raw_writer,
        notice_writer=notice_writer,
        error_writer=error_writer,
    )
    pipeline = WriterDispatchPipeline(writer_bundle=bundle)
    spider = _SpiderStub()

    pipeline.process_item(
        RawDocumentItem(item_type=ITEM_TYPE_RAW_DOCUMENT, source_code="s", crawl_job_id=None),
        spider,
    )
    pipeline.process_item(
        TenderNoticeItem(item_type=ITEM_TYPE_TENDER_NOTICE, source_code="s", crawl_job_id=None),
        spider,
    )
    pipeline.process_item(
        NoticeVersionItem(item_type=ITEM_TYPE_NOTICE_VERSION, source_code="s", crawl_job_id=None),
        spider,
    )
    pipeline.process_item(
        TenderAttachmentItem(item_type=ITEM_TYPE_TENDER_ATTACHMENT, source_code="s", crawl_job_id=None),
        spider,
    )
    pipeline.process_item(
        CrawlErrorItem(item_type=ITEM_TYPE_CRAWL_ERROR, source_code="s", crawl_job_id=None),
        spider,
    )

    assert len(raw_writer.payloads) == 1
    assert len(notice_writer.notice_payloads) == 1
    assert len(notice_writer.version_payloads) == 1
    assert len(notice_writer.attachment_payloads) == 1
    assert len(error_writer.payloads) == 1
