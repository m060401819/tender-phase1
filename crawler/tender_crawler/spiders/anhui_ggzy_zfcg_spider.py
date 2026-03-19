from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import scrapy

from tender_crawler.items import (
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_ATTACHMENT,
    ITEM_TYPE_TENDER_NOTICE,
    NoticeVersionItem,
    RawDocumentItem,
    TenderAttachmentItem,
    TenderNoticeItem,
)
from tender_crawler.parsers import AnhuiGgzyZfcgParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider
from tender_crawler.utils import normalize_url, sha256_text


class AnhuiGgzyZfcgSpider(BaseSourceSpider):
    """Real source sample: Anhui government procurement notices."""

    name = "anhui_ggzy_zfcg"
    source_code = "anhui_ggzy_zfcg"
    allowed_domains = ["ggzy.ah.gov.cn"]
    start_urls = ["https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1"]

    parser_cls = AnhuiGgzyZfcgParser

    sub_detail_url = "https://ggzy.ah.gov.cn/zfcg/newDetailSub"

    def __init__(
        self,
        max_pages: int = 1,
        bulletin_nature: str = "1",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_pages = max(1, int(max_pages))
        self.bulletin_nature = str(bulletin_nature)

    def parse(self, response: scrapy.http.Response):
        current_page = self._current_page(response)

        yield self._build_raw_item(
            response=response,
            raw_html=response.text,
            raw_url=response.url,
            role="list",
            extra_meta={
                "list_page_url": response.url,
                "current_page": current_page,
            },
        )

        seen_detail_urls: set[str] = set()
        for anchor in response.css("a[href*='/zfcg/newDetail']"):
            href = (anchor.attrib.get("href") or "").strip()
            if not href:
                continue

            detail_url = response.urljoin(href)
            if detail_url in seen_detail_urls:
                continue
            seen_detail_urls.add(detail_url)

            list_item_title = self._clean_text(" ".join(anchor.css("::text").getall()))
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                errback=self.handle_request_error,
                cb_kwargs={
                    "list_page_url": response.url,
                    "list_item_title": list_item_title,
                },
            )

        max_page_no = self._max_page_no(response)
        if current_page < min(max_page_no, self.max_pages):
            next_page = current_page + 1
            yield scrapy.FormRequest(
                url=response.urljoin("/zfcg/list"),
                formdata={
                    "currentPage": str(next_page),
                    "time": "1",
                    "bulletinNature": self.bulletin_nature,
                },
                callback=self.parse,
                errback=self.handle_request_error,
            )

    def parse_detail(
        self,
        response: scrapy.http.Response,
        list_page_url: str,
        list_item_title: str,
    ):
        guid = self._extract_guid(response.url)
        if not guid:
            yield self._build_error_item(
                stage="parse",
                url=response.url,
                error_type="MissingGuid",
                error_message="detail url missing guid query parameter",
                traceback_text="",
                retryable=False,
            )
            return

        yield self._build_raw_item(
            response=response,
            raw_html=response.text,
            raw_url=response.url,
            role="detail",
            extra_meta={
                "list_page_url": list_page_url,
                "detail_page_url": response.url,
                "guid": guid,
                "list_item_title": list_item_title,
            },
        )

        yield scrapy.FormRequest(
            url=self.sub_detail_url,
            formdata={
                "type": "xmdj",
                "bulletinNature": self.bulletin_nature,
                "guid": guid,
                "statusGuid": "",
            },
            callback=self.parse_xmdj,
            errback=self.handle_request_error,
            cb_kwargs={
                "guid": guid,
                "detail_url": response.url,
                "detail_html": response.text,
                "list_page_url": list_page_url,
                "list_item_title": list_item_title,
            },
        )

    def parse_xmdj(
        self,
        response: scrapy.http.Response,
        guid: str,
        detail_url: str,
        detail_html: str,
        list_page_url: str,
        list_item_title: str,
    ):
        xmdj_url = f"{detail_url}&subType=xmdj"
        yield self._build_raw_item(
            response=response,
            raw_html=response.text,
            raw_url=xmdj_url,
            role="detail_sub_xmdj",
            extra_meta={
                "guid": guid,
                "detail_page_url": detail_url,
                "list_page_url": list_page_url,
            },
        )

        yield scrapy.FormRequest(
            url=self.sub_detail_url,
            formdata={
                "type": "bulletin",
                "bulletinNature": self.bulletin_nature,
                "guid": guid,
                "statusGuid": "",
            },
            callback=self.parse_bulletin,
            errback=self.handle_request_error,
            cb_kwargs={
                "guid": guid,
                "detail_url": detail_url,
                "detail_html": detail_html,
                "xmdj_html": response.text,
                "list_page_url": list_page_url,
                "list_item_title": list_item_title,
            },
        )

    def parse_bulletin(
        self,
        response: scrapy.http.Response,
        guid: str,
        detail_url: str,
        detail_html: str,
        xmdj_html: str,
        list_page_url: str,
        list_item_title: str,
    ):
        bulletin_url = f"{detail_url}&subType=bulletin"
        bulletin_raw_item = self._build_raw_item(
            response=response,
            raw_html=response.text,
            raw_url=bulletin_url,
            role="detail_sub_bulletin",
            extra_meta={
                "guid": guid,
                "detail_page_url": detail_url,
                "list_page_url": list_page_url,
            },
        )
        yield bulletin_raw_item

        try:
            parsed = self.parser.parse_notice(
                detail_url=detail_url,
                list_page_url=list_page_url,
                list_item_title=list_item_title,
                detail_html=detail_html,
                xmdj_html=xmdj_html,
                bulletin_html=response.text,
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            yield self._build_error_item(
                stage="parse",
                url=detail_url,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                traceback_text="",
                retryable=False,
            )
            return

        notice_dedup_hash = sha256_text(
            f"{self.source_code}|{parsed.external_id or ''}|{parsed.title}|{normalize_url(detail_url)}"
        )
        bulletin_content_hash = sha256_text(response.text)

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
            source_site_name=parsed.source_site_name,
            source_site_url=parsed.source_site_url,
            list_page_url=parsed.list_page_url,
            detail_page_url=parsed.detail_page_url,
            content_text=parsed.content_text,
            source_url=detail_url,
            raw_content_hash=bulletin_content_hash,
        )
        yield notice_item

        bulletin_url_hash = sha256_text(normalize_url(bulletin_url))
        version_item = NoticeVersionItem(
            item_type=ITEM_TYPE_NOTICE_VERSION,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            notice_dedup_hash=notice_dedup_hash,
            notice_external_id=parsed.external_id,
            version_no=1,
            is_current=True,
            content_hash=bulletin_content_hash,
            title=parsed.title,
            notice_type=parsed.notice_type,
            issuer=parsed.issuer,
            region=parsed.region,
            published_at=parsed.published_at.isoformat() if parsed.published_at else None,
            deadline_at=parsed.deadline_at.isoformat() if parsed.deadline_at else None,
            budget_amount=str(parsed.budget_amount) if parsed.budget_amount is not None else None,
            budget_currency=parsed.budget_currency,
            source_site_name=parsed.source_site_name,
            source_site_url=parsed.source_site_url,
            list_page_url=parsed.list_page_url,
            detail_page_url=parsed.detail_page_url,
            content_text=parsed.content_text,
            structured_data=parsed.structured_data,
            change_summary=parsed.change_summary,
            raw_document_url_hash=bulletin_url_hash,
        )
        yield version_item

        for attachment in parsed.attachments:
            file_url = response.urljoin(attachment.file_url)
            file_name = attachment.file_name or file_url.rsplit("/", maxsplit=1)[-1] or "attachment"
            attachment_item = TenderAttachmentItem(
                item_type=ITEM_TYPE_TENDER_ATTACHMENT,
                source_code=self.source_code,
                crawl_job_id=self.crawl_job_id,
                notice_dedup_hash=notice_dedup_hash,
                notice_external_id=parsed.external_id,
                notice_version_no=None,
                file_name=file_name,
                attachment_type=attachment.attachment_type,
                file_url=file_url,
                url_hash=sha256_text(normalize_url(file_url)),
                file_hash=attachment.file_hash,
                storage_uri=attachment.storage_uri,
                mime_type=attachment.mime_type,
                file_ext=file_name.rsplit(".", maxsplit=1)[-1] if "." in file_name else None,
                file_size_bytes=attachment.file_size_bytes,
                published_at=parsed.published_at.isoformat() if parsed.published_at else None,
                source_url=detail_url,
            )
            yield attachment_item

    def _build_raw_item(
        self,
        *,
        response: scrapy.http.Response,
        raw_html: str,
        raw_url: str,
        role: str,
        extra_meta: dict[str, Any],
    ) -> RawDocumentItem:
        normalized = normalize_url(raw_url)
        return RawDocumentItem(
            item_type=ITEM_TYPE_RAW_DOCUMENT,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            url=raw_url,
            normalized_url=normalized,
            url_hash=sha256_text(normalized),
            content_hash=sha256_text(raw_html),
            document_type="html",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            storage_uri="",
            raw_body=raw_html,
            http_status=response.status,
            mime_type=response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore"),
            charset=response.encoding,
            title=self._clean_text(response.css("title::text,#title::text").get()) or None,
            content_length=len(raw_html.encode("utf-8")),
            extra_meta={
                "role": role,
                **extra_meta,
            },
        )

    def _current_page(self, response: scrapy.http.Response) -> int:
        raw = response.css("#currentPage::attr(value)").get()
        try:
            return int(raw) if raw else 1
        except ValueError:
            return 1

    def _max_page_no(self, response: scrapy.http.Response) -> int:
        numbers: list[int] = []
        for text in response.css(".gcxxfy a::text").getall():
            stripped = self._clean_text(text)
            if stripped.isdigit():
                numbers.append(int(stripped))
        return max(numbers) if numbers else self._current_page(response)

    def _extract_guid(self, url: str) -> str | None:
        query = parse_qs(urlsplit(url).query)
        guid = query.get("guid", [None])[0]
        return guid

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        return " ".join(value.split())
