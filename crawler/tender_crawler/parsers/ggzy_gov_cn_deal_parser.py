from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from scrapy.http import TextResponse

from tender_crawler.parsers.base import BaseNoticeParser, ParsedAttachment, ParsedNotice
from tender_crawler.services import DeduplicationService
from tender_crawler.utils import normalize_url, sha256_text

DEDUP_SERVICE = DeduplicationService()

_MEANINGLESS_TITLE_SUFFIX_RE = re.compile(
    r"(?:[\s\-—_:：,，。；;·]+)?"
    r"(?:采购|招标|竞争性磋商|竞争性谈判|询价|中标|成交|结果|更正|澄清|终止|废标|流标)?"
    r"(?:公告|公示|通知|信息)$",
    flags=re.IGNORECASE,
)
_MEANINGLESS_TITLE_TRAILING_TOKENS = (
    "采购",
    "招标",
    "竞争性磋商",
    "竞争性谈判",
    "询价",
    "中标",
    "成交",
    "结果",
    "更正",
    "澄清",
    "终止",
    "废标",
    "流标",
)


@dataclass(slots=True)
class GgzyGovCnDealListRecord:
    title: str
    normalized_title: str | None
    published_date: str | None
    published_at_iso: str | None
    province: str | None
    source_platform: str | None
    issuer: str | None
    notice_type: str
    detail_url: str | None
    normalized_detail_url: str | None
    external_id: str | None
    source_duplicate_key: str
    source_list_item_fingerprint: str
    list_item_content_hash: str
    list_item_raw: dict[str, Any]


class GgzyGovCnDealParser(BaseNoticeParser):
    """Parser for ggzy.gov.cn government procurement aggregation list/detail pages."""

    source_site_name = "全国公共资源交易平台（政府采购）"
    source_site_url = "https://www.ggzy.gov.cn/"

    def parse_list_record(
        self,
        *,
        record: dict[str, Any],
        source_code: str,
        list_page_url: str,
    ) -> GgzyGovCnDealListRecord | None:
        title = self._normalize_text(record.get("title") or record.get("titleShow"))
        if title is None:
            return None

        raw_url = self._normalize_text(
            record.get("url")
            or record.get("detailUrl")
            or record.get("linkUrl")
        )
        detail_url = None
        normalized_detail_url = None
        if raw_url is not None:
            detail_url = normalize_url(urljoin(self.source_site_url, raw_url))
            normalized_detail_url = DEDUP_SERVICE.normalize_detail_url(detail_url)

        published_text = self._normalize_text(
            record.get("publishTime")
            or record.get("publishedAt")
            or record.get("publishDate")
        )
        published_date = DEDUP_SERVICE.normalize_published_date(published_text)
        published_at_iso = f"{published_date}T00:00:00+00:00" if published_date else None

        province = self._normalize_text(record.get("provinceText") or record.get("province"))
        source_platform = self._normalize_text(
            record.get("transactionSourcesPlatformText")
            or record.get("sourcePlatform")
            or record.get("platformName")
        )
        issuer = self._normalize_text(record.get("issuer") or record.get("publisher") or source_platform)

        info_text = self._normalize_text(
            record.get("informationTypeText")
            or record.get("infoType")
            or record.get("businessTypeText")
        )
        notice_type = self._infer_notice_type(title=title, info_text=info_text)

        normalized_title = self.normalize_title_for_source_dedup(title)
        external_id = self._extract_external_id(record=record, detail_url=detail_url)

        source_duplicate_key = self._build_source_duplicate_key(
            source_code=source_code,
            normalized_detail_url=normalized_detail_url,
            province=province,
            source_platform=source_platform,
            normalized_title=normalized_title,
            published_date=published_date,
        )
        source_list_item_fingerprint = self._build_source_list_item_fingerprint(
            source_code=source_code,
            normalized_detail_url=normalized_detail_url,
            province=province,
            source_platform=source_platform,
            normalized_title=normalized_title,
            published_date=published_date,
        )

        list_item_content_hash = sha256_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )

        return GgzyGovCnDealListRecord(
            title=title,
            normalized_title=normalized_title,
            published_date=published_date,
            published_at_iso=published_at_iso,
            province=province,
            source_platform=source_platform,
            issuer=issuer,
            notice_type=notice_type,
            detail_url=detail_url,
            normalized_detail_url=normalized_detail_url,
            external_id=external_id,
            source_duplicate_key=source_duplicate_key,
            source_list_item_fingerprint=source_list_item_fingerprint,
            list_item_content_hash=list_item_content_hash,
            list_item_raw=dict(record),
        )

    def parse_detail_notice(
        self,
        *,
        response: TextResponse,
        list_record: GgzyGovCnDealListRecord,
        list_page_url: str,
    ) -> ParsedNotice:
        body_text = self._extract_detail_text(response)
        title = self._normalize_text(response.css("title::text,#title::text").get()) or list_record.title
        published_at = (
            DEDUP_SERVICE.parse_datetime_like(list_record.published_at_iso)
            or DEDUP_SERVICE.parse_datetime_like(list_record.published_date)
        )
        attachments = self._extract_detail_attachments(response)

        structured_data: dict[str, Any] = {
            "source_site_name": self.source_site_name,
            "source_site_url": self.source_site_url,
            "list_page_url": list_page_url,
            "detail_page_url": response.url,
            "source_platform": list_record.source_platform,
            "province": list_record.province,
            "notice_type": list_record.notice_type,
            "list_item_raw": list_record.list_item_raw,
        }

        return ParsedNotice(
            title=title,
            notice_type=list_record.notice_type,
            external_id=list_record.external_id,
            issuer=list_record.issuer,
            region=list_record.province,
            published_at=published_at,
            budget_currency="CNY",
            summary=(body_text[:2000] if body_text else None),
            content_text=body_text,
            source_site_name=self.source_site_name,
            source_site_url=self.source_site_url,
            list_page_url=list_page_url,
            detail_page_url=response.url,
            structured_data=structured_data,
            attachments=attachments,
        )

    def normalize_title_for_source_dedup(self, value: str | None) -> str | None:
        normalized = self._normalize_text(value)
        if normalized is None:
            return None

        normalized = unicodedata.normalize("NFKC", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        while True:
            updated = _MEANINGLESS_TITLE_SUFFIX_RE.sub("", normalized).strip()
            if updated == normalized:
                break
            normalized = updated

        # Drop common trailing business tokens even when no explicit "公告/公示" suffix exists.
        while True:
            stripped = normalized.rstrip("-—_:：,，。；;· ").strip()
            lowered = stripped.lower()
            matched = False
            for token in _MEANINGLESS_TITLE_TRAILING_TOKENS:
                token_lower = token.lower()
                if lowered.endswith(token_lower):
                    stripped = stripped[: -len(token)].rstrip("-—_:：,，。；;· ").strip()
                    matched = True
                    break
            normalized = stripped
            if not matched:
                break

        normalized = normalized.rstrip("-—_:：,，。；;· ").strip()
        normalized = normalized.replace(" ", "")
        normalized = re.sub(r"\s+", " ", normalized)
        if not normalized:
            return None
        return normalized.lower()

    def _build_source_duplicate_key(
        self,
        *,
        source_code: str,
        normalized_detail_url: str | None,
        province: str | None,
        source_platform: str | None,
        normalized_title: str | None,
        published_date: str | None,
    ) -> str:
        if normalized_detail_url:
            return sha256_text(f"{source_code}|detail_url|{normalized_detail_url}")

        seed = "|".join(
            [
                source_code,
                self._normalize_identity_text(province),
                self._normalize_identity_text(source_platform),
                normalized_title or "-",
                published_date or "-",
            ]
        )
        return sha256_text(seed)

    def _build_source_list_item_fingerprint(
        self,
        *,
        source_code: str,
        normalized_detail_url: str | None,
        province: str | None,
        source_platform: str | None,
        normalized_title: str | None,
        published_date: str | None,
    ) -> str:
        if normalized_detail_url:
            return sha256_text(f"{source_code}|fingerprint|{normalized_detail_url}")

        seed = "|".join(
            [
                source_code,
                self._normalize_identity_text(province),
                self._normalize_identity_text(source_platform),
                normalized_title or "-",
                published_date or "-",
            ]
        )
        return sha256_text(seed)

    def _extract_external_id(self, *, record: dict[str, Any], detail_url: str | None) -> str | None:
        for key in (
            "id",
            "infoId",
            "infoID",
            "noticeId",
            "noticeID",
            "dealId",
            "dealID",
            "guid",
            "uuid",
        ):
            value = self._normalize_text(record.get(key))
            if value:
                return value

        if not detail_url:
            return None

        query = parse_qs(urlsplit(detail_url).query)
        for key in ("id", "guid", "noticeId", "detailId"):
            values = query.get(key)
            if not values:
                continue
            value = self._normalize_text(values[0])
            if value:
                return value

        locator = DEDUP_SERVICE.extract_detail_locator(detail_url=detail_url)
        if locator and locator != DEDUP_SERVICE.normalize_detail_url(detail_url):
            return locator
        return None

    def _extract_detail_text(self, response: TextResponse) -> str | None:
        candidates = response.css(
            "#zoom *::text, .article *::text, .content *::text, .detail *::text, body *::text"
        ).getall()
        parts = [self._normalize_text(item) for item in candidates]
        merged = "\n".join(part for part in parts if part)
        merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
        return merged or None

    def _extract_detail_attachments(self, response: TextResponse) -> list[ParsedAttachment]:
        attachments: list[ParsedAttachment] = []
        seen_urls: set[str] = set()

        for anchor in response.css("a[href]"):
            href = self._normalize_text(anchor.attrib.get("href"))
            if not href:
                continue

            link_text = self._normalize_text(" ".join(anchor.css("::text").getall()))
            file_url = urljoin(response.url, href)
            lowered = file_url.lower()

            looks_file = lowered.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z"))
            looks_attachment = bool(link_text and ("附件" in link_text or "下载" in link_text))
            if not looks_file and not looks_attachment:
                continue

            normalized = normalize_url(file_url)
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)

            attachment = self.build_attachment(
                file_url=file_url,
                base_url=response.url,
                link_text=link_text,
                attachment_type="notice_file",
            )
            if attachment is None:
                continue
            attachments.append(attachment)

        return attachments

    def _infer_notice_type(self, *, title: str, info_text: str | None) -> str:
        combined = f"{title} {info_text or ''}"
        if any(keyword in combined for keyword in ("更正", "变更", "澄清", "延期", "终止", "废标", "流标")):
            return "change"
        if any(keyword in combined for keyword in ("中标", "成交", "结果", "合同")):
            return "result"
        return "announcement"

    def _normalize_identity_text(self, value: str | None) -> str:
        normalized = self._normalize_text(value)
        if normalized is None:
            return "-"
        normalized = unicodedata.normalize("NFKC", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized or "-"

    def _normalize_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value)
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None
        return text

    def _parse_datetime(self, value: str | None) -> datetime | None:
        normalized = self._normalize_text(value)
        if normalized is None:
            return None
        parsed = DEDUP_SERVICE.parse_datetime_like(normalized)
        if parsed is not None:
            return parsed
        try:
            return datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
