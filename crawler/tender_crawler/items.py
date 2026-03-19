from __future__ import annotations

from itemadapter import ItemAdapter
import scrapy

ITEM_TYPE_RAW_DOCUMENT = "raw_document"
ITEM_TYPE_TENDER_NOTICE = "tender_notice"
ITEM_TYPE_NOTICE_VERSION = "notice_version"
ITEM_TYPE_TENDER_ATTACHMENT = "tender_attachment"
ITEM_TYPE_CRAWL_ERROR = "crawl_error"

ITEM_TYPES = {
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_NOTICE,
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_TENDER_ATTACHMENT,
    ITEM_TYPE_CRAWL_ERROR,
}


class BaseCrawlItem(scrapy.Item):
    """Shared fields for all crawler items."""

    item_type = scrapy.Field()
    source_code = scrapy.Field()
    crawl_job_id = scrapy.Field()


class RawDocumentItem(BaseCrawlItem):
    """Raw page/archive metadata; maps to `raw_document`."""

    url = scrapy.Field()
    normalized_url = scrapy.Field()
    url_hash = scrapy.Field()
    content_hash = scrapy.Field()
    document_type = scrapy.Field()
    fetched_at = scrapy.Field()

    storage_uri = scrapy.Field()
    raw_body = scrapy.Field()

    http_status = scrapy.Field()
    mime_type = scrapy.Field()
    charset = scrapy.Field()
    title = scrapy.Field()
    content_length = scrapy.Field()
    extra_meta = scrapy.Field()


class TenderNoticeItem(BaseCrawlItem):
    """Structured notice current snapshot; maps to `tender_notice`."""

    external_id = scrapy.Field()
    project_code = scrapy.Field()
    dedup_hash = scrapy.Field()

    title = scrapy.Field()
    notice_type = scrapy.Field()
    issuer = scrapy.Field()
    region = scrapy.Field()

    published_at = scrapy.Field()
    deadline_at = scrapy.Field()
    budget_amount = scrapy.Field()
    budget_currency = scrapy.Field()
    summary = scrapy.Field()

    source_site_name = scrapy.Field()
    source_site_url = scrapy.Field()
    list_page_url = scrapy.Field()
    detail_page_url = scrapy.Field()
    content_text = scrapy.Field()

    source_url = scrapy.Field()
    raw_content_hash = scrapy.Field()


class NoticeVersionItem(BaseCrawlItem):
    """Notice version snapshot; maps to `notice_version`."""

    notice_dedup_hash = scrapy.Field()
    notice_external_id = scrapy.Field()

    version_no = scrapy.Field()
    is_current = scrapy.Field()

    content_hash = scrapy.Field()
    title = scrapy.Field()
    notice_type = scrapy.Field()
    issuer = scrapy.Field()
    region = scrapy.Field()

    published_at = scrapy.Field()
    deadline_at = scrapy.Field()
    budget_amount = scrapy.Field()
    budget_currency = scrapy.Field()

    source_site_name = scrapy.Field()
    source_site_url = scrapy.Field()
    list_page_url = scrapy.Field()
    detail_page_url = scrapy.Field()
    content_text = scrapy.Field()

    structured_data = scrapy.Field()
    change_summary = scrapy.Field()
    raw_document_url_hash = scrapy.Field()


class TenderAttachmentItem(BaseCrawlItem):
    """Attachment metadata; maps to `tender_attachment`."""

    notice_dedup_hash = scrapy.Field()
    notice_external_id = scrapy.Field()
    notice_version_no = scrapy.Field()

    file_name = scrapy.Field()
    attachment_type = scrapy.Field()
    file_url = scrapy.Field()
    url_hash = scrapy.Field()
    file_hash = scrapy.Field()

    storage_uri = scrapy.Field()
    mime_type = scrapy.Field()
    file_ext = scrapy.Field()
    file_size_bytes = scrapy.Field()
    published_at = scrapy.Field()
    downloaded_at = scrapy.Field()

    source_url = scrapy.Field()


class CrawlErrorItem(BaseCrawlItem):
    """Crawl/parse/persist errors; maps to `crawl_error`."""

    stage = scrapy.Field()
    url = scrapy.Field()
    error_type = scrapy.Field()
    error_message = scrapy.Field()
    traceback = scrapy.Field()
    retryable = scrapy.Field()
    occurred_at = scrapy.Field()


def get_item_type(item: object) -> str | None:
    """Safely read item type from any Scrapy-compatible item."""
    return ItemAdapter(item).get("item_type")
