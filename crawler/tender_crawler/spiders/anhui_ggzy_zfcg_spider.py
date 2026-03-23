from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from parsel import Selector
import scrapy
from scrapy.http import Response, TextResponse

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
from tender_crawler.services import DeduplicationService
from tender_crawler.spiders.base_source_spider import BaseSourceSpider
from tender_crawler.utils import normalize_url, sha256_text

DEDUP_SERVICE = DeduplicationService()
FormDataValue = str | Iterable[str]
FormData = dict[str, FormDataValue]


@dataclass(slots=True)
class _ListItemCandidate:
    detail_url: str
    title: str
    published_at: str | None
    region: str | None
    notice_type: str
    source_list_item_fingerprint: str
    source_duplicate_key: str


class AnhuiGgzyZfcgSpider(BaseSourceSpider):
    """Real source sample: Anhui government procurement notices."""

    name = "anhui_ggzy_zfcg"
    source_code = "anhui_ggzy_zfcg"
    allowed_domains = ["ggzy.ah.gov.cn"]
    start_urls = ["https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1"]

    parser_cls: type[AnhuiGgzyZfcgParser] = AnhuiGgzyZfcgParser
    parser: AnhuiGgzyZfcgParser

    sub_detail_url = "https://ggzy.ah.gov.cn/zfcg/newDetailSub"

    def __init__(
        self,
        max_pages: int | None = None,
        bulletin_nature: str = "1",
        time: str | None = None,
        backfill_year: int | None = None,
        stop_after_consecutive_no_new_pages: int = 5,
        stop_after_consecutive_empty_pages: int | None = None,
        dedup_within_run: str | bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.max_pages = self._parse_optional_positive_int(max_pages)
        self.bulletin_nature = str(bulletin_nature)
        self.backfill_year = self._parse_optional_positive_int(backfill_year)
        self.backfill_start_date = (
            date(self.backfill_year, 1, 1)
            if self.backfill_year is not None
            else None
        )
        self.time_filter = self._resolve_time_filter(raw_time=time, backfill_year=self.backfill_year)

        threshold = stop_after_consecutive_no_new_pages
        threshold_override = self._parse_optional_positive_int(stop_after_consecutive_empty_pages)
        if threshold_override is not None:
            threshold = threshold_override
        self.stop_after_consecutive_no_new_pages = max(1, int(threshold))
        self.dedup_within_run = self._as_bool(dedup_within_run, default=True)

        self.start_urls = [self._build_list_url(page=1)]

        self._seen_source_list_item_fingerprints: set[str] = set()
        self._seen_list_pages: set[int] = set()

        self.pages_scraped = 0
        self.list_items_seen = 0
        self.list_items_unique = 0
        self.list_items_source_duplicates_skipped = 0
        self._consecutive_no_new_pages = 0
        self._first_publish_date_seen: date | None = None
        self._last_publish_date_seen: date | None = None

    def parse(self, response: Response):
        text_response = self._require_text_response(response)
        current_page = self._current_page(text_response)
        max_page_no = self._max_page_no(text_response)

        if current_page in self._seen_list_pages:
            self.logger.warning(
                "list page repeated; stop to avoid loop: current_page_no=%s page_url=%s",
                current_page,
                text_response.url,
            )
            return
        self._seen_list_pages.add(current_page)
        self.pages_scraped += 1

        try:
            list_items = self._extract_list_items(text_response)
        except Exception as exc:  # pragma: no cover - defensive branch
            yield self._build_error_item(
                stage="parse",
                url=text_response.url,
                error_type=exc.__class__.__name__,
                error_message=f"parse list failed: {exc}",
                traceback_text="",
                retryable=True,
            )
            return

        page_item_count = len(list_items)
        self.list_items_seen += page_item_count
        page_publish_min, page_publish_max = self._publish_date_range(list_items)
        self._merge_publish_date_range(page_publish_min, page_publish_max)
        all_items_older_than_backfill = self._all_items_older_than_backfill(list_items)

        filtered_items = [item for item in list_items if self._is_in_backfill_window(item.published_at)]
        page_items_filtered_out_by_backfill = page_item_count - len(filtered_items)
        new_unique_item_count = 0
        page_source_duplicates_skipped = 0

        if not all_items_older_than_backfill:
            for candidate in filtered_items:
                if (
                    self.dedup_within_run
                    and candidate.source_list_item_fingerprint in self._seen_source_list_item_fingerprints
                ):
                    page_source_duplicates_skipped += 1
                    continue

                self._seen_source_list_item_fingerprints.add(candidate.source_list_item_fingerprint)
                new_unique_item_count += 1

                yield scrapy.Request(
                    url=candidate.detail_url,
                    callback=self.parse_detail,
                    errback=self.handle_request_error,
                    cb_kwargs={
                        "list_page_url": text_response.url,
                        "list_item_title": candidate.title,
                        "list_item_published_at": candidate.published_at,
                        "list_item_region": candidate.region,
                        "list_item_notice_type": candidate.notice_type,
                        "source_list_item_fingerprint": candidate.source_list_item_fingerprint,
                        "list_source_duplicate_key": candidate.source_duplicate_key,
                    },
                )

        self.list_items_unique += new_unique_item_count
        self.list_items_source_duplicates_skipped += page_source_duplicates_skipped

        if new_unique_item_count == 0:
            self._consecutive_no_new_pages += 1
        else:
            self._consecutive_no_new_pages = 0

        next_page = self._next_page_no(response=text_response, current_page=current_page)
        has_next_control = next_page is not None
        page_state = (
            f"max_page_no={max_page_no},has_next_control={has_next_control},next_page={next_page},"
            f"backfill_year={self.backfill_year}"
        )
        self.logger.info(
            "list pagination: current_page_no=%s page_url=%s page_state=%s page_item_count=%s new_unique_item_count=%s",
            current_page,
            text_response.url,
            page_state,
            page_item_count,
            new_unique_item_count,
        )

        first_publish_date_seen = self._first_publish_date_seen.isoformat() if self._first_publish_date_seen else None
        last_publish_date_seen = self._last_publish_date_seen.isoformat() if self._last_publish_date_seen else None
        yield self._build_raw_item(
            response=text_response,
            raw_html=text_response.text,
            raw_url=text_response.url,
            role="list",
            extra_meta={
                "list_page_url": text_response.url,
                "current_page": current_page,
                "max_page_no": max_page_no,
                "pages_scraped_total": self.pages_scraped,
                "page_item_count": page_item_count,
                "page_items_filtered_out_by_backfill": page_items_filtered_out_by_backfill,
                "new_unique_item_count": new_unique_item_count,
                "page_source_duplicates_skipped": page_source_duplicates_skipped,
                "list_items_seen_total": self.list_items_seen,
                "list_items_unique_total": self.list_items_unique,
                "list_items_source_duplicates_skipped_total": self.list_items_source_duplicates_skipped,
                "list_page_publish_date_min": page_publish_min.isoformat() if page_publish_min else None,
                "list_page_publish_date_max": page_publish_max.isoformat() if page_publish_max else None,
                "first_publish_date_seen_total": first_publish_date_seen,
                "last_publish_date_seen_total": last_publish_date_seen,
                "all_items_older_than_backfill": all_items_older_than_backfill,
                "stop_after_consecutive_no_new_pages": self.stop_after_consecutive_no_new_pages,
                "page_state": page_state,
            },
        )

        if page_item_count == 0:
            self.logger.info(
                "stop pagination by empty list page: current_page_no=%s",
                current_page,
            )
            return

        if all_items_older_than_backfill:
            self.logger.info(
                "stop pagination by backfill boundary: current_page_no=%s backfill_start=%s",
                current_page,
                self.backfill_start_date.isoformat() if self.backfill_start_date else "-",
            )
            return

        if self.max_pages is not None and self.pages_scraped >= self.max_pages:
            self.logger.info(
                "stop pagination by max_pages: current_page_no=%s max_pages=%s",
                current_page,
                self.max_pages,
            )
            return

        if self._consecutive_no_new_pages >= self.stop_after_consecutive_no_new_pages:
            self.logger.info(
                "stop pagination by consecutive no-new pages: current_page_no=%s consecutive_no_new_pages=%s threshold=%s",
                current_page,
                self._consecutive_no_new_pages,
                self.stop_after_consecutive_no_new_pages,
            )
            return

        if next_page is None:
            self.logger.info(
                "stop pagination by last page: current_page_no=%s max_page_no=%s has_next_control=%s",
                current_page,
                max_page_no,
                has_next_control,
            )
            return

        yield scrapy.FormRequest(
            url=text_response.urljoin("/zfcg/list"),
            formdata=self._build_list_formdata(next_page),
            callback=self.parse,
            errback=self.handle_request_error,
            cb_kwargs={},
        )

    def parse_detail(
        self,
        response: Response,
        list_page_url: str,
        list_item_title: str,
        list_item_published_at: str | None = None,
        list_item_region: str | None = None,
        list_item_notice_type: str | None = None,
        source_list_item_fingerprint: str | None = None,
        list_source_duplicate_key: str | None = None,
    ):
        text_response = self._require_text_response(response)
        guid = self._extract_guid(text_response.url)
        if not guid:
            yield self._build_error_item(
                stage="parse",
                url=text_response.url,
                error_type="MissingGuid",
                error_message="detail url missing guid query parameter",
                traceback_text="",
                retryable=False,
            )
            return

        yield self._build_raw_item(
            response=text_response,
            raw_html=text_response.text,
            raw_url=text_response.url,
            role="detail",
            source_duplicate_key=list_source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
            extra_meta={
                "list_page_url": list_page_url,
                "detail_page_url": text_response.url,
                "guid": guid,
                "list_item_title": list_item_title,
                "published_at": list_item_published_at,
                "region": list_item_region,
                "notice_type": list_item_notice_type,
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
                "detail_url": text_response.url,
                "detail_html": text_response.text,
                "list_page_url": list_page_url,
                "list_item_title": list_item_title,
                "list_item_published_at": list_item_published_at,
                "list_item_region": list_item_region,
                "list_item_notice_type": list_item_notice_type,
                "source_list_item_fingerprint": source_list_item_fingerprint,
                "list_source_duplicate_key": list_source_duplicate_key,
            },
        )

    def parse_xmdj(
        self,
        response: Response,
        guid: str,
        detail_url: str,
        detail_html: str,
        list_page_url: str,
        list_item_title: str,
        list_item_published_at: str | None = None,
        list_item_region: str | None = None,
        list_item_notice_type: str | None = None,
        source_list_item_fingerprint: str | None = None,
        list_source_duplicate_key: str | None = None,
    ):
        text_response = self._require_text_response(response)
        xmdj_url = f"{detail_url}&subType=xmdj"
        yield self._build_raw_item(
            response=text_response,
            raw_html=text_response.text,
            raw_url=xmdj_url,
            role="detail_sub_xmdj",
            source_duplicate_key=list_source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
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
                "xmdj_html": text_response.text,
                "list_page_url": list_page_url,
                "list_item_title": list_item_title,
                "list_item_published_at": list_item_published_at,
                "list_item_region": list_item_region,
                "list_item_notice_type": list_item_notice_type,
                "source_list_item_fingerprint": source_list_item_fingerprint,
                "list_source_duplicate_key": list_source_duplicate_key,
            },
        )

    def parse_bulletin(
        self,
        response: Response,
        guid: str,
        detail_url: str,
        detail_html: str,
        xmdj_html: str,
        list_page_url: str,
        list_item_title: str,
        list_item_published_at: str | None = None,
        list_item_region: str | None = None,
        list_item_notice_type: str | None = None,
        source_list_item_fingerprint: str | None = None,
        list_source_duplicate_key: str | None = None,
    ):
        text_response = self._require_text_response(response)
        bulletin_url = f"{detail_url}&subType=bulletin"
        bulletin_raw_item = self._build_raw_item(
            response=text_response,
            raw_html=text_response.text,
            raw_url=bulletin_url,
            role="detail_sub_bulletin",
            source_duplicate_key=list_source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
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
                list_item_published_at=list_item_published_at,
                detail_html=detail_html,
                xmdj_html=xmdj_html,
                bulletin_html=text_response.text,
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

        normalized_published_date = (
            DEDUP_SERVICE.normalize_published_date(parsed.published_at or list_item_published_at)
            if (parsed.published_at or list_item_published_at)
            else None
        )
        resolved_published_at = (
            parsed.published_at.isoformat()
            if parsed.published_at is not None
            else self._publish_date_to_iso_datetime(normalized_published_date)
        )
        resolved_region = parsed.region or list_item_region
        resolved_notice_type = parsed.notice_type or list_item_notice_type
        resolved_source_duplicate_key = list_source_duplicate_key or DEDUP_SERVICE.build_source_duplicate_key(
            source_code=self.source_code,
            title=parsed.title,
            detail_url=detail_url,
            published_at=normalized_published_date,
            issuer=parsed.issuer,
            budget_amount=parsed.budget_amount,
            detail_id=guid,
            notice_type=resolved_notice_type,
            region=resolved_region,
        )
        persistence_dedup_key = DEDUP_SERVICE.build_persistence_dedup_key(
            title=parsed.title,
            published_at=normalized_published_date,
            purchaser=None,
            publisher=parsed.issuer,
            budget_amount=parsed.budget_amount,
            region=resolved_region,
            detail_url=detail_url,
            detail_id=guid,
        )

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
            dedup_key=persistence_dedup_key,
            source_duplicate_key=resolved_source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
            title=parsed.title,
            notice_type=resolved_notice_type,
            issuer=parsed.issuer,
            region=resolved_region,
            published_at=resolved_published_at,
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
            dedup_key=persistence_dedup_key,
            source_duplicate_key=resolved_source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
            version_no=1,
            is_current=True,
            content_hash=bulletin_content_hash,
            title=parsed.title,
            notice_type=resolved_notice_type,
            issuer=parsed.issuer,
            region=resolved_region,
            published_at=resolved_published_at,
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
                published_at=resolved_published_at,
                source_url=detail_url,
            )
            yield attachment_item

    def _build_raw_item(
        self,
        *,
        response: TextResponse,
        raw_html: str,
        raw_url: str,
        role: str,
        extra_meta: dict[str, Any],
        source_duplicate_key: str | None = None,
        source_list_item_fingerprint: str | None = None,
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
            mime_type=self._decode_header_value(response.headers.get("Content-Type")),
            charset=response.encoding,
            title=self._clean_text(response.css("title::text,#title::text").get()) or None,
            content_length=len(raw_html.encode("utf-8")),
            source_duplicate_key=source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
            extra_meta={
                "role": role,
                **extra_meta,
            },
        )

    def _extract_list_items(self, response: TextResponse) -> list[_ListItemCandidate]:
        items: list[_ListItemCandidate] = []
        for anchor in response.css("a[href*='/zfcg/newDetail']"):
            href = (anchor.attrib.get("href") or "").strip()
            if not href:
                continue

            detail_url = response.urljoin(href)
            title = self._clean_text(" ".join(anchor.css("::text").getall()))
            if not title:
                continue

            context_text = self._extract_anchor_context_text(anchor)
            sibling_date_text = self._clean_text(
                anchor.xpath("ancestor::li[1]//span[contains(@class,'date')]//text()").get()
            )
            published_at = (
                self._extract_published_at(sibling_date_text)
                or self._extract_published_at(context_text)
                or self._extract_published_at(title)
            )
            region = self._extract_region(title, context_text)
            notice_type = self._infer_notice_type(title)
            guid = self._extract_guid(detail_url)

            source_list_item_fingerprint = DEDUP_SERVICE.build_source_list_item_fingerprint(
                source_code=self.source_code,
                title=title,
                detail_url=detail_url,
                published_at=published_at,
                notice_type=notice_type,
                region=region,
                include_detail_locator=False,
            )
            source_duplicate_key = DEDUP_SERVICE.build_source_duplicate_key(
                source_code=self.source_code,
                title=title,
                detail_url=detail_url,
                published_at=published_at,
                detail_id=guid,
                notice_type=notice_type,
                region=region,
            )

            items.append(
                _ListItemCandidate(
                    detail_url=detail_url,
                    title=title,
                    published_at=published_at,
                    region=region,
                    notice_type=notice_type,
                    source_list_item_fingerprint=source_list_item_fingerprint,
                    source_duplicate_key=source_duplicate_key,
                )
            )
        return items

    def _extract_anchor_context_text(self, anchor: Selector) -> str:
        context_nodes = anchor.xpath("ancestor::*[self::li or self::tr or self::div][1]//text()").getall()
        if not context_nodes:
            context_nodes = anchor.xpath("../..//text()").getall()
        return self._clean_text(" ".join(context_nodes))

    def _extract_published_at(self, text: str) -> str | None:
        if not text:
            return None
        match = re.search(
            r"([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2}(?:\s*[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)",
            text,
        )
        if match is None:
            return None
        return DEDUP_SERVICE.normalize_published_date(match.group(1))

    def _extract_region(self, title: str, context_text: str) -> str | None:
        for source_text in (title, context_text):
            match = re.search(r"【([^】]+)】", source_text)
            if match:
                region = self._clean_text(match.group(1))
                if region:
                    return region
        return None

    def _infer_notice_type(self, title: str) -> str:
        if any(key in title for key in ("更正", "变更", "澄清", "延期")):
            return "change"
        if any(key in title for key in ("中标", "成交", "结果", "中选")):
            return "result"
        return "announcement"

    def _next_page_no(self, response: TextResponse, current_page: int) -> int | None:
        for anchor in response.css(".gcxxfy a"):
            text = self._clean_text(" ".join(anchor.css("::text").getall()))
            if "下一页" not in text:
                continue
            class_name = (anchor.attrib.get("class") or "").lower()
            href = (anchor.attrib.get("href") or "").strip().lower()
            onclick = (anchor.attrib.get("onclick") or "").strip().lower()
            disabled = "disabled" in class_name
            noop_href = href in {"", "#", "javascript:void(0)", "javascript:;"}
            if disabled or (noop_href and not onclick):
                return None

            target = self._parse_pagination_target(onclick) or self._parse_pagination_target(href)
            if target is not None and target > current_page:
                return target
            return current_page + 1
        return None

    def _parse_pagination_target(self, raw: str) -> int | None:
        if not raw:
            return None
        match = re.search(r"pagination\(([^)]+)\)", raw, flags=re.IGNORECASE)
        if match is None:
            return None
        expr = re.sub(r"\s+", "", match.group(1))
        if not expr:
            return None
        if expr.isdigit():
            return int(expr)
        if not re.fullmatch(r"[0-9+\-]+", expr):
            return None

        total = 0
        current = ""
        sign = 1
        for ch in expr:
            if ch in {"+", "-"}:
                if not current:
                    return None
                total += sign * int(current)
                current = ""
                sign = 1 if ch == "+" else -1
                continue
            current += ch

        if not current:
            return None
        total += sign * int(current)
        return total if total > 0 else None

    def _current_page(self, response: TextResponse) -> int:
        raw = response.css(
            "#currentPage::attr(value),input[name='currentPage']::attr(value),#pageNo::attr(value),input[name='pageNo']::attr(value)"
        ).get()
        try:
            return int(raw) if raw else 1
        except ValueError:
            return 1

    def _max_page_no(self, response: TextResponse) -> int:
        numbers: list[int] = []
        for text in response.css(".gcxxfy a::text,.gcxxfy span::text").getall():
            stripped = self._clean_text(text)
            if stripped.isdigit():
                numbers.append(int(stripped))

        for input_selector in response.css("input"):
            name = (input_selector.attrib.get("name") or "").strip().lower()
            input_id = (input_selector.attrib.get("id") or "").strip().lower()
            if not any(token in name or token in input_id for token in ("totalpage", "pagecount")):
                continue
            raw_value = self._clean_text(input_selector.attrib.get("value"))
            if not raw_value:
                continue
            try:
                numbers.append(int(raw_value))
            except ValueError:
                continue

        return max(numbers) if numbers else self._current_page(response)

    def _build_list_url(self, *, page: int) -> str:
        query: list[tuple[str, str]] = [("bulletinNature", self.bulletin_nature)]
        if self.time_filter is not None:
            query.append(("time", self.time_filter))
        if page > 1:
            query.append(("currentPage", str(page)))
        return f"https://ggzy.ah.gov.cn/zfcg/list?{urlencode(query)}"

    def _build_list_formdata(self, page: int) -> FormData:
        formdata: FormData = {
            "currentPage": str(page),
            "bulletinNature": self.bulletin_nature,
        }
        if self.time_filter is not None:
            formdata["time"] = self.time_filter
        return formdata

    def _resolve_time_filter(self, *, raw_time: str | None, backfill_year: int | None) -> str | None:
        normalized = self._as_str(raw_time)
        if normalized is not None:
            return normalized
        if backfill_year is not None:
            return ""
        return "1"

    def _is_in_backfill_window(self, published_at: str | None) -> bool:
        if self.backfill_start_date is None:
            return True
        published_date = self._as_date(published_at)
        if published_date is None:
            return True
        return published_date >= self.backfill_start_date

    def _all_items_older_than_backfill(self, items: list[_ListItemCandidate]) -> bool:
        if self.backfill_start_date is None:
            return False
        if not items:
            return False

        has_parseable = False
        for item in items:
            published_date = self._as_date(item.published_at)
            if published_date is None:
                return False
            has_parseable = True
            if published_date >= self.backfill_start_date:
                return False
        return has_parseable

    def _publish_date_range(self, items: list[_ListItemCandidate]) -> tuple[date | None, date | None]:
        parsed_dates = [self._as_date(item.published_at) for item in items]
        values = [value for value in parsed_dates if value is not None]
        if not values:
            return None, None
        return min(values), max(values)

    def _merge_publish_date_range(self, minimum: date | None, maximum: date | None) -> None:
        if minimum is not None:
            if self._last_publish_date_seen is None or minimum < self._last_publish_date_seen:
                self._last_publish_date_seen = minimum
        if maximum is not None:
            if self._first_publish_date_seen is None or maximum > self._first_publish_date_seen:
                self._first_publish_date_seen = maximum

    def _publish_date_to_iso_datetime(self, value: str | None) -> str | None:
        normalized = DEDUP_SERVICE.normalize_published_date(value)
        if normalized is None:
            return None
        return f"{normalized}T00:00:00+00:00"

    def _as_date(self, value: str | None) -> date | None:
        normalized = DEDUP_SERVICE.normalize_published_date(value)
        if normalized is None:
            return None
        try:
            return date.fromisoformat(normalized)
        except ValueError:
            return None

    def _parse_optional_positive_int(self, value: Any) -> int | None:
        normalized = self._as_str(value)
        if normalized is None:
            return None
        parsed = int(normalized)
        return max(1, parsed)

    def _extract_guid(self, url: str) -> str | None:
        query = parse_qs(urlsplit(url).query)
        guid = query.get("guid", [None])[0]
        return guid

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        return " ".join(value.split())

    def _as_str(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _as_bool(self, value: str | bool, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y"}:
            return True
        if text in {"0", "false", "no", "n"}:
            return False
        return default
