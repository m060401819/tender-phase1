from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import scrapy
from twisted.python.failure import Failure

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
from tender_crawler.parsers import BaseNoticeParser
from tender_crawler.utils import normalize_url, sha256_text


class BaseSourceSpider(scrapy.Spider):
    """Base spider enforcing crawl -> parse -> item flow separation."""

    source_code = "base_source"
    parser_cls = BaseNoticeParser

    def __init__(self, crawl_job_id: int | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.crawl_job_id = int(crawl_job_id) if crawl_job_id is not None else None
        self.parser = self.parser_cls()

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                errback=self.handle_request_error,
                dont_filter=True,
            )

    def parse(self, response: scrapy.http.Response):
        fetched_at = datetime.now(timezone.utc)
        normalized_url = normalize_url(response.url)
        raw_body = response.text or ""
        url_hash = sha256_text(normalized_url)
        content_hash = sha256_text(raw_body)

        raw_item = RawDocumentItem(
            item_type=ITEM_TYPE_RAW_DOCUMENT,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            url=response.url,
            normalized_url=normalized_url,
            url_hash=url_hash,
            content_hash=content_hash,
            document_type="html",
            fetched_at=fetched_at.isoformat(),
            storage_uri="",
            raw_body=raw_body,
            http_status=response.status,
            mime_type=response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore"),
            charset=response.encoding,
            title=response.css("title::text").get(default="").strip() or None,
            content_length=len(raw_body.encode("utf-8")),
            extra_meta={"source_url": response.url},
        )
        yield raw_item

        try:
            parsed = self.parser.parse(response)
        except Exception as exc:  # pragma: no cover - covered by behavior, not exact branch
            yield self._build_error_item(
                stage="parse",
                url=response.url,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                traceback_text="",
                retryable=False,
            )
            return

        notice_dedup_hash = sha256_text(
            f"{self.source_code}|{parsed.external_id or ''}|{parsed.title}|{normalized_url}"
        )

        notice_item = TenderNoticeItem(
            item_type=ITEM_TYPE_TENDER_NOTICE,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            external_id=parsed.external_id,
            project_code=parsed.project_code,
            dedup_hash=notice_dedup_hash,
            title=parsed.title,
            notice_type=parsed.notice_type,
            issuer=parsed.issuer,
            region=parsed.region,
            published_at=parsed.published_at.isoformat() if parsed.published_at else None,
            deadline_at=parsed.deadline_at.isoformat() if parsed.deadline_at else None,
            budget_amount=str(parsed.budget_amount) if parsed.budget_amount is not None else None,
            budget_currency=parsed.budget_currency,
            summary=parsed.summary,
            source_url=response.url,
            raw_content_hash=content_hash,
        )
        yield notice_item

        version_item = NoticeVersionItem(
            item_type=ITEM_TYPE_NOTICE_VERSION,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            notice_dedup_hash=notice_dedup_hash,
            notice_external_id=parsed.external_id,
            version_no=1,
            is_current=True,
            content_hash=content_hash,
            title=parsed.title,
            notice_type=parsed.notice_type,
            issuer=parsed.issuer,
            region=parsed.region,
            published_at=parsed.published_at.isoformat() if parsed.published_at else None,
            deadline_at=parsed.deadline_at.isoformat() if parsed.deadline_at else None,
            budget_amount=str(parsed.budget_amount) if parsed.budget_amount is not None else None,
            budget_currency=parsed.budget_currency,
            structured_data=parsed.structured_data,
            change_summary=parsed.change_summary,
            raw_document_url_hash=url_hash,
        )
        yield version_item

        for attachment in parsed.attachments:
            file_url = response.urljoin(attachment.file_url)
            attachment_item = TenderAttachmentItem(
                item_type=ITEM_TYPE_TENDER_ATTACHMENT,
                source_code=self.source_code,
                crawl_job_id=self.crawl_job_id,
                notice_dedup_hash=notice_dedup_hash,
                notice_external_id=parsed.external_id,
                notice_version_no=1,
                file_name=attachment.file_name,
                attachment_type=attachment.attachment_type,
                file_url=file_url,
                url_hash=sha256_text(normalize_url(file_url)),
                file_hash=attachment.file_hash,
                storage_uri=attachment.storage_uri,
                mime_type=attachment.mime_type,
                file_ext=(attachment.file_name.rsplit(".", maxsplit=1)[-1] if "." in attachment.file_name else None),
                file_size_bytes=attachment.file_size_bytes,
                published_at=parsed.published_at.isoformat() if parsed.published_at else None,
                source_url=response.url,
            )
            yield attachment_item

    def handle_request_error(self, failure: Failure):
        request_url = failure.request.url if failure.request else None
        error_type = failure.type.__name__ if failure.type else "RequestError"
        yield self._build_error_item(
            stage="fetch",
            url=request_url,
            error_type=error_type,
            error_message=str(failure.value),
            traceback_text=failure.getTraceback(),
            retryable=True,
        )

    def _build_error_item(
        self,
        stage: str,
        url: str | None,
        error_type: str,
        error_message: str,
        traceback_text: str,
        retryable: bool,
    ) -> CrawlErrorItem:
        return CrawlErrorItem(
            item_type=ITEM_TYPE_CRAWL_ERROR,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            stage=stage,
            url=url,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback_text,
            retryable=retryable,
            occurred_at=datetime.now(timezone.utc).isoformat(),
        )
