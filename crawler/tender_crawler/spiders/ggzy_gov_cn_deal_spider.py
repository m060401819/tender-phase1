from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
from typing import Any

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
from tender_crawler.parsers import GgzyGovCnDealListRecord, GgzyGovCnDealParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider
from tender_crawler.utils import normalize_url, sha256_text

FormDataValue = str | Iterable[str]
FormData = dict[str, FormDataValue]


class GgzyGovCnDealSpider(BaseSourceSpider):
    """Crawler for national public resource trading platform government procurement aggregation."""

    name = "ggzy_gov_cn_deal"
    source_code = "ggzy_gov_cn_deal"
    allowed_domains = ["ggzy.gov.cn", "www.ggzy.gov.cn"]
    start_urls = ["https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02"]

    parser_cls: type[GgzyGovCnDealParser] = GgzyGovCnDealParser
    parser: GgzyGovCnDealParser

    list_api_url = "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList"
    browser_user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        max_pages: int | None = None,
        backfill_year: int | None = None,
        job_type: str = "manual",
        source_type: str = "1",
        deal_classify: str = "02",
        deal_stage: str = "0200",
        deal_time: str | None = None,
        keyword: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.job_type = (str(job_type).strip().lower() or "manual")
        if self.job_type not in {"manual", "manual_retry", "backfill"}:
            self.job_type = "manual"

        self.max_pages = self._parse_optional_positive_int(max_pages)
        self.backfill_year = self._parse_optional_positive_int(backfill_year)

        self.source_type = self._as_str(source_type) or "1"
        self.deal_classify = self._as_str(deal_classify) or "02"
        self.deal_stage = self._as_str(deal_stage) or "0200"
        self.keyword = self._as_str(keyword) or ""
        self.time_begin: str | None = None
        self.time_end: str | None = None

        if self.job_type == "backfill" or self.backfill_year is not None:
            self.backfill_year = self.backfill_year or datetime.now(timezone.utc).year
            self.deal_time = self._as_str(deal_time) or "06"
            self.time_begin = f"{self.backfill_year}-01-01"
            self.time_end = f"{self.backfill_year}-12-31"
        else:
            self.deal_time = self._as_str(deal_time) or "02"
            self.time_begin = None
            self.time_end = None

        self._seen_source_duplicate_keys: set[str] = set()

        self.pages_scraped = 0
        self.list_items_seen = 0
        self.list_items_unique = 0
        self.list_items_source_duplicates_skipped = 0

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url=url,
                headers=self._build_page_headers(referer=None),
                callback=self.parse_landing,
                errback=self.handle_request_error,
                dont_filter=True,
            )

    def parse_landing(self, response: Response):
        text_response = self._require_text_response(response)
        yield self._build_raw_item(
            response=text_response,
            raw_body=text_response.text,
            raw_url=text_response.url,
            role="landing",
            extra_meta={
                "job_type": self.job_type,
                "deal_time": self.deal_time,
                "deal_classify": self.deal_classify,
                "deal_stage": self.deal_stage,
                "source_type": self.source_type,
                "backfill_year": self.backfill_year,
            },
        )

        yield self._build_list_request(page=1, list_page_url=text_response.url)

    def _build_list_request(self, *, page: int, list_page_url: str) -> scrapy.FormRequest:
        return scrapy.FormRequest(
            url=self.list_api_url,
            method="POST",
            formdata=self._build_list_formdata(page=page),
            headers=self._build_ajax_headers(referer=list_page_url),
            callback=self.parse_list_page,
            errback=self.handle_request_error,
            cb_kwargs={
                "page": page,
                "list_page_url": list_page_url,
            },
            dont_filter=True,
        )

    def parse_list_page(self, response: Response, page: int, list_page_url: str):
        text_response = self._require_text_response(response)
        self.pages_scraped += 1

        payload: dict[str, Any] = {}
        parse_error_message = None
        try:
            payload_raw = json.loads(text_response.text)
            if isinstance(payload_raw, dict):
                payload = payload_raw
            else:
                parse_error_message = "列表解析失败: 响应JSON不是对象"
        except json.JSONDecodeError as exc:
            parse_error_message = f"列表解析失败: 响应不是JSON ({exc})"

        code = int(payload.get("code") or 0) if payload else 0
        api_message = self._as_str(payload.get("message")) if payload else None
        data_raw = payload.get("data")
        data: dict[str, Any] = data_raw if isinstance(data_raw, dict) else {}
        records_raw = data.get("records")
        record_entries: list[object] = records_raw if isinstance(records_raw, list) else []

        page_item_count = len(record_entries)
        self.list_items_seen += page_item_count

        emitted_unique = 0
        page_source_duplicates_skipped = 0

        if parse_error_message is None and code == 200:
            for raw_record in record_entries:
                if not isinstance(raw_record, dict):
                    continue
                parsed_record = self.parser.parse_list_record(
                    record=raw_record,
                    source_code=self.source_code,
                    list_page_url=list_page_url,
                )
                if parsed_record is None:
                    continue

                if parsed_record.source_duplicate_key in self._seen_source_duplicate_keys:
                    page_source_duplicates_skipped += 1
                    continue

                self._seen_source_duplicate_keys.add(parsed_record.source_duplicate_key)
                emitted_unique += 1

                yield self._build_list_notice_item(parsed_record=parsed_record, list_page_url=list_page_url)
                yield self._build_list_version_item(parsed_record=parsed_record, list_page_url=list_page_url)

                if parsed_record.detail_url:
                    yield scrapy.Request(
                        url=parsed_record.detail_url,
                        headers=self._build_page_headers(referer=list_page_url),
                        callback=self.parse_detail,
                        errback=self.handle_request_error,
                        cb_kwargs={
                            "list_page_url": list_page_url,
                            "record": self._serialize_record(parsed_record),
                        },
                    )
        elif parse_error_message is None and code == 829:
            parse_error_message = "页面获取失败: 列表接口触发验证码，当前实现不破解验证码"
        elif parse_error_message is None and code != 200:
            parse_error_message = f"页面获取失败: 列表接口返回 code={code} message={api_message or '-'}"

        self.list_items_unique += emitted_unique
        self.list_items_source_duplicates_skipped += page_source_duplicates_skipped

        total = self._as_int(data.get("total")) if isinstance(data, dict) else None
        pages = self._as_int(data.get("pages")) if isinstance(data, dict) else None
        current = self._as_int(data.get("current")) if isinstance(data, dict) else page

        yield self._build_raw_item(
            response=text_response,
            raw_body=text_response.text,
            raw_url=f"{self.list_api_url}?page={page}&deal_time={self.deal_time}&deal_classify={self.deal_classify}",
            role="list",
            extra_meta={
                "list_page_url": list_page_url,
                "current_page": page,
                "api_code": code,
                "api_message": api_message,
                "api_total": total,
                "api_pages": pages,
                "api_current": current,
                "page_item_count": page_item_count,
                "new_unique_item_count": emitted_unique,
                "page_source_duplicates_skipped": page_source_duplicates_skipped,
                "list_items_seen_total": self.list_items_seen,
                "list_items_unique_total": self.list_items_unique,
                "list_items_source_duplicates_skipped_total": self.list_items_source_duplicates_skipped,
                "job_type": self.job_type,
                "max_pages": self.max_pages,
                "backfill_year": self.backfill_year,
                "parse_error": parse_error_message,
            },
        )

        if parse_error_message is not None:
            stage = "fetch" if parse_error_message.startswith("页面获取失败") else "parse"
            yield self._build_error_item(
                stage=stage,
                url=text_response.url,
                error_type="ListPageError",
                error_message=parse_error_message,
                traceback_text="",
                retryable=True,
            )
            return

        if self.max_pages is not None and page >= self.max_pages:
            return

        if pages is not None and pages > 0 and page < pages:
            yield self._build_list_request(page=page + 1, list_page_url=list_page_url)

    def parse_detail(self, response: Response, list_page_url: str, record: dict[str, Any]):
        text_response = self._require_text_response(response)
        parsed_record = self._deserialize_record(record)

        yield self._build_raw_item(
            response=text_response,
            raw_body=text_response.text,
            raw_url=text_response.url,
            role="detail",
            source_duplicate_key=parsed_record.source_duplicate_key,
            source_list_item_fingerprint=parsed_record.source_list_item_fingerprint,
            extra_meta={
                "list_page_url": list_page_url,
                "detail_page_url": text_response.url,
                "external_id": parsed_record.external_id,
                "title": parsed_record.title,
                "province": parsed_record.province,
                "source_platform": parsed_record.source_platform,
                "notice_type": parsed_record.notice_type,
            },
        )

        detail_error_message = self._extract_detail_error_message(text_response)
        if detail_error_message is not None:
            yield self._build_error_item(
                stage="fetch",
                url=text_response.url,
                error_type="DetailPageError",
                error_message=detail_error_message,
                traceback_text="",
                retryable=True,
            )
            return

        try:
            parsed_notice = self.parser.parse_detail_notice(
                response=text_response,
                list_record=parsed_record,
                list_page_url=list_page_url,
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            yield self._build_error_item(
                stage="parse",
                url=text_response.url,
                error_type=exc.__class__.__name__,
                error_message=f"详情解析失败: {exc}",
                traceback_text="",
                retryable=False,
            )
            return

        detail_content_hash = sha256_text(text_response.text)
        dedup_hash = sha256_text(f"{self.source_code}|{parsed_record.source_duplicate_key}")

        notice_item = TenderNoticeItem(
            item_type=ITEM_TYPE_TENDER_NOTICE,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            external_id=parsed_notice.external_id,
            project_code=parsed_notice.project_code,
            dedup_hash=dedup_hash,
            dedup_key=parsed_record.source_duplicate_key,
            source_duplicate_key=parsed_record.source_duplicate_key,
            source_list_item_fingerprint=parsed_record.source_list_item_fingerprint,
            title=parsed_notice.title,
            notice_type=parsed_notice.notice_type,
            issuer=parsed_notice.issuer,
            region=parsed_notice.region,
            published_at=parsed_notice.published_at.isoformat() if parsed_notice.published_at else parsed_record.published_at_iso,
            deadline_at=parsed_notice.deadline_at.isoformat() if parsed_notice.deadline_at else None,
            budget_amount=str(parsed_notice.budget_amount) if parsed_notice.budget_amount is not None else None,
            budget_currency=parsed_notice.budget_currency,
            summary=parsed_notice.summary,
            source_site_name=parsed_notice.source_site_name,
            source_site_url=parsed_notice.source_site_url,
            list_page_url=parsed_notice.list_page_url,
            detail_page_url=parsed_notice.detail_page_url,
            content_text=parsed_notice.content_text,
            source_url=parsed_notice.detail_page_url,
            raw_content_hash=detail_content_hash,
        )
        yield notice_item

        version_item = NoticeVersionItem(
            item_type=ITEM_TYPE_NOTICE_VERSION,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            notice_dedup_hash=dedup_hash,
            notice_external_id=parsed_notice.external_id,
            dedup_key=parsed_record.source_duplicate_key,
            source_duplicate_key=parsed_record.source_duplicate_key,
            source_list_item_fingerprint=parsed_record.source_list_item_fingerprint,
            version_no=1,
            is_current=True,
            content_hash=detail_content_hash,
            title=parsed_notice.title,
            notice_type=parsed_notice.notice_type,
            issuer=parsed_notice.issuer,
            region=parsed_notice.region,
            published_at=parsed_notice.published_at.isoformat() if parsed_notice.published_at else parsed_record.published_at_iso,
            deadline_at=parsed_notice.deadline_at.isoformat() if parsed_notice.deadline_at else None,
            budget_amount=str(parsed_notice.budget_amount) if parsed_notice.budget_amount is not None else None,
            budget_currency=parsed_notice.budget_currency,
            source_site_name=parsed_notice.source_site_name,
            source_site_url=parsed_notice.source_site_url,
            list_page_url=parsed_notice.list_page_url,
            detail_page_url=parsed_notice.detail_page_url,
            content_text=parsed_notice.content_text,
            structured_data=parsed_notice.structured_data,
            change_summary=parsed_notice.change_summary,
            raw_document_url_hash=sha256_text(normalize_url(text_response.url)),
        )
        yield version_item

        for attachment in parsed_notice.attachments:
            file_url = normalize_url(text_response.urljoin(attachment.file_url))
            file_name = attachment.file_name or file_url.rsplit("/", maxsplit=1)[-1] or "attachment"
            yield TenderAttachmentItem(
                item_type=ITEM_TYPE_TENDER_ATTACHMENT,
                source_code=self.source_code,
                crawl_job_id=self.crawl_job_id,
                notice_dedup_hash=dedup_hash,
                notice_external_id=parsed_notice.external_id,
                notice_version_no=None,
                file_name=file_name,
                attachment_type=attachment.attachment_type,
                file_url=file_url,
                url_hash=sha256_text(file_url),
                file_hash=attachment.file_hash,
                storage_uri=attachment.storage_uri,
                mime_type=attachment.mime_type,
                file_ext=file_name.rsplit(".", maxsplit=1)[-1] if "." in file_name else None,
                file_size_bytes=attachment.file_size_bytes,
                published_at=parsed_notice.published_at.isoformat() if parsed_notice.published_at else parsed_record.published_at_iso,
                source_url=text_response.url,
            )

    def _build_page_headers(self, *, referer: str | None) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "User-Agent": self.browser_user_agent,
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _build_ajax_headers(self, *, referer: str) -> dict[str, str]:
        headers = self._build_page_headers(referer=referer)
        headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        return headers

    def _extract_detail_error_message(self, response: TextResponse) -> str | None:
        payload = self._parse_json_payload(response.text)
        if payload is None:
            return None

        if isinstance(payload, dict):
            code = self._as_int(payload.get("code"))
            message = self._as_str(payload.get("message")) or self._as_str(payload.get("msg")) or "-"
            if code is not None:
                return f"详情获取失败: 详情页返回JSON code={code} message={message}"

        return "详情获取失败: 详情页返回 JSON 响应，当前未返回可解析 HTML"

    def _parse_json_payload(self, raw_text: str) -> object | None:
        stripped = raw_text.lstrip()
        if not stripped or stripped[0] not in ("{", "["):
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    def _build_list_formdata(self, *, page: int) -> FormData:
        formdata: FormData = {
            "SOURCE_TYPE": self.source_type,
            "DEAL_TIME": self.deal_time,
            "PAGENUMBER": str(page),
            "isShowAll": "1",
            "FINDTXT": self.keyword,
        }
        if self.deal_classify != "00":
            formdata["DEAL_CLASSIFY"] = self.deal_classify
        if self._should_include_stage(self.deal_stage):
            formdata["DEAL_STAGE"] = self.deal_stage
        if self.deal_time == "06" and self.time_begin and self.time_end:
            formdata["TIMEBEGIN"] = self.time_begin
            formdata["TIMEEND"] = self.time_end
        return formdata

    def _should_include_stage(self, stage: str) -> bool:
        normalized = (stage or "").strip()
        if not normalized:
            return False
        # Keep consistent with the page JS: "不限" stage values are omitted in request payload.
        if len(normalized) >= 4 and normalized[2:4] == "00":
            return False
        if len(normalized) >= 6 and normalized[4:6] == "00":
            return False
        return True

    def _build_list_notice_item(self, *, parsed_record: GgzyGovCnDealListRecord, list_page_url: str) -> TenderNoticeItem:
        dedup_hash = sha256_text(f"{self.source_code}|{parsed_record.source_duplicate_key}")
        return TenderNoticeItem(
            item_type=ITEM_TYPE_TENDER_NOTICE,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            external_id=parsed_record.external_id,
            project_code=None,
            dedup_hash=dedup_hash,
            dedup_key=parsed_record.source_duplicate_key,
            source_duplicate_key=parsed_record.source_duplicate_key,
            source_list_item_fingerprint=parsed_record.source_list_item_fingerprint,
            title=parsed_record.title,
            notice_type=parsed_record.notice_type,
            issuer=parsed_record.issuer,
            region=parsed_record.province,
            published_at=parsed_record.published_at_iso,
            deadline_at=None,
            budget_amount=None,
            budget_currency="CNY",
            summary=None,
            source_site_name=self.parser.source_site_name,
            source_site_url=self.parser.source_site_url,
            list_page_url=list_page_url,
            detail_page_url=parsed_record.detail_url,
            content_text=None,
            source_url=parsed_record.detail_url or list_page_url,
            raw_content_hash=parsed_record.list_item_content_hash,
        )

    def _build_list_version_item(self, *, parsed_record: GgzyGovCnDealListRecord, list_page_url: str) -> NoticeVersionItem:
        dedup_hash = sha256_text(f"{self.source_code}|{parsed_record.source_duplicate_key}")
        return NoticeVersionItem(
            item_type=ITEM_TYPE_NOTICE_VERSION,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            notice_dedup_hash=dedup_hash,
            notice_external_id=parsed_record.external_id,
            dedup_key=parsed_record.source_duplicate_key,
            source_duplicate_key=parsed_record.source_duplicate_key,
            source_list_item_fingerprint=parsed_record.source_list_item_fingerprint,
            version_no=1,
            is_current=True,
            content_hash=parsed_record.list_item_content_hash,
            title=parsed_record.title,
            notice_type=parsed_record.notice_type,
            issuer=parsed_record.issuer,
            region=parsed_record.province,
            published_at=parsed_record.published_at_iso,
            deadline_at=None,
            budget_amount=None,
            budget_currency="CNY",
            source_site_name=self.parser.source_site_name,
            source_site_url=self.parser.source_site_url,
            list_page_url=list_page_url,
            detail_page_url=parsed_record.detail_url,
            content_text=None,
            structured_data={
                "source_platform": parsed_record.source_platform,
                "province": parsed_record.province,
                "list_item_raw": parsed_record.list_item_raw,
            },
            change_summary="list-draft",
            raw_document_url_hash=sha256_text(
                normalize_url(parsed_record.detail_url or f"{self.list_api_url}?list_page={list_page_url}")
            ),
        )

    def _build_raw_item(
        self,
        *,
        response: TextResponse,
        raw_body: str,
        raw_url: str,
        role: str,
        extra_meta: dict[str, Any],
        source_duplicate_key: str | None = None,
        source_list_item_fingerprint: str | None = None,
    ) -> RawDocumentItem:
        normalized = normalize_url(raw_url)
        title_value: str | None = None
        try:
            title_value = self._clean_text(response.css("title::text").get()) or None
        except Exception:
            title_value = None
        return RawDocumentItem(
            item_type=ITEM_TYPE_RAW_DOCUMENT,
            source_code=self.source_code,
            crawl_job_id=self.crawl_job_id,
            url=raw_url,
            normalized_url=normalized,
            url_hash=sha256_text(normalized),
            content_hash=sha256_text(raw_body),
            document_type="html",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            storage_uri="",
            raw_body=raw_body,
            http_status=response.status,
            mime_type=self._decode_header_value(response.headers.get("Content-Type")),
            charset=response.encoding,
            title=title_value,
            content_length=len(raw_body.encode("utf-8")),
            source_duplicate_key=source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
            extra_meta={"role": role, **extra_meta},
        )

    def _serialize_record(self, record: GgzyGovCnDealListRecord) -> dict[str, Any]:
        return {
            "title": record.title,
            "normalized_title": record.normalized_title,
            "published_date": record.published_date,
            "published_at_iso": record.published_at_iso,
            "province": record.province,
            "source_platform": record.source_platform,
            "issuer": record.issuer,
            "notice_type": record.notice_type,
            "detail_url": record.detail_url,
            "normalized_detail_url": record.normalized_detail_url,
            "external_id": record.external_id,
            "source_duplicate_key": record.source_duplicate_key,
            "source_list_item_fingerprint": record.source_list_item_fingerprint,
            "list_item_content_hash": record.list_item_content_hash,
            "list_item_raw": record.list_item_raw,
        }

    def _deserialize_record(self, data: dict[str, Any]) -> GgzyGovCnDealListRecord:
        raw_list_item = data.get("list_item_raw")
        list_item_raw = {str(key): value for key, value in raw_list_item.items()} if isinstance(raw_list_item, dict) else {}
        return GgzyGovCnDealListRecord(
            title=str(data.get("title") or ""),
            normalized_title=self._as_str(data.get("normalized_title")),
            published_date=self._as_str(data.get("published_date")),
            published_at_iso=self._as_str(data.get("published_at_iso")),
            province=self._as_str(data.get("province")),
            source_platform=self._as_str(data.get("source_platform")),
            issuer=self._as_str(data.get("issuer")),
            notice_type=self._as_str(data.get("notice_type")) or "announcement",
            detail_url=self._as_str(data.get("detail_url")),
            normalized_detail_url=self._as_str(data.get("normalized_detail_url")),
            external_id=self._as_str(data.get("external_id")),
            source_duplicate_key=self._as_str(data.get("source_duplicate_key")) or sha256_text("missing-source-dup-key"),
            source_list_item_fingerprint=self._as_str(data.get("source_list_item_fingerprint"))
            or sha256_text("missing-list-fingerprint"),
            list_item_content_hash=self._as_str(data.get("list_item_content_hash")) or sha256_text("missing-content"),
            list_item_raw=list_item_raw,
        )

    def _parse_optional_positive_int(self, value: Any) -> int | None:
        normalized = self._as_str(value)
        if normalized is None:
            return None
        parsed = int(normalized)
        return max(1, parsed)

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        return " ".join(value.split())

    def _as_str(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _as_int(self, value: object) -> int | None:
        normalized = self._as_str(value)
        if normalized is None:
            return None
        try:
            return int(normalized)
        except ValueError:
            return None
