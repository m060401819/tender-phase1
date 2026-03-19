from __future__ import annotations

import re
from dataclasses import dataclass

from tender_crawler.utils import normalize_url, sha256_text

NOTICE_TYPES = {"announcement", "change", "result"}


@dataclass(slots=True)
class NoticeIdentity:
    dedup_hash: str | None
    external_id: str | None
    normalized_detail_url: str | None
    normalized_title: str | None
    merge_strategy: str


class DeduplicationService:
    """Cross-source normalization, dedup and version identity helpers."""

    def normalize_notice_type(self, value: object) -> str:
        text = self._as_str(value)
        if text in NOTICE_TYPES:
            return text
        return "announcement"

    def normalize_url_and_hash(
        self,
        *,
        url: object,
        normalized_url: object | None = None,
    ) -> tuple[str | None, str | None]:
        raw_url = self._as_str(normalized_url) or self._as_str(url)
        if not raw_url:
            return None, None
        normalized = normalize_url(raw_url)
        return normalized, sha256_text(normalized)

    def ensure_content_hash(self, *, content_hash: object, raw_body: object) -> str | None:
        existing = self._as_str(content_hash)
        if existing:
            return existing
        body = self._as_str(raw_body)
        if not body:
            return None
        return sha256_text(body)

    def build_notice_identity(self, item: dict[str, object]) -> NoticeIdentity:
        source_code = self._as_str(item.get("source_code")) or "unknown_source"
        external_id = self._as_str(item.get("external_id") or item.get("notice_external_id"))
        detail_url = self._as_str(item.get("detail_page_url") or item.get("source_url") or item.get("url"))
        title = self._normalize_title(self._as_str(item.get("title")))

        normalized_detail_url = None
        if detail_url:
            normalized_detail_url = normalize_url(detail_url)

        if external_id:
            merge_strategy = "external_id"
            dedup_seed = f"{source_code}|external_id|{external_id}"
        elif normalized_detail_url:
            merge_strategy = "detail_url"
            dedup_seed = f"{source_code}|detail_url|{normalized_detail_url}"
        elif title:
            merge_strategy = "title"
            dedup_seed = f"{source_code}|title|{title}"
        else:
            merge_strategy = "fallback"
            provided_dedup = self._as_str(item.get("dedup_hash") or item.get("notice_dedup_hash"))
            if provided_dedup:
                return NoticeIdentity(
                    dedup_hash=provided_dedup,
                    external_id=external_id,
                    normalized_detail_url=normalized_detail_url,
                    normalized_title=title,
                    merge_strategy="provided",
                )
            return NoticeIdentity(
                dedup_hash=None,
                external_id=external_id,
                normalized_detail_url=normalized_detail_url,
                normalized_title=title,
                merge_strategy=merge_strategy,
            )

        return NoticeIdentity(
            dedup_hash=sha256_text(dedup_seed),
            external_id=external_id,
            normalized_detail_url=normalized_detail_url,
            normalized_title=title,
            merge_strategy=merge_strategy,
        )

    def normalize_notice_item(self, item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        identity = self.build_notice_identity(normalized)
        normalized["dedup_hash"] = identity.dedup_hash
        normalized["notice_dedup_hash"] = identity.dedup_hash
        normalized["external_id"] = identity.external_id
        normalized["notice_external_id"] = identity.external_id
        normalized["notice_type"] = self.normalize_notice_type(normalized.get("notice_type"))
        normalized["content_hash"] = self.ensure_content_hash(
            content_hash=normalized.get("content_hash") or normalized.get("raw_content_hash"),
            raw_body=normalized.get("content_text"),
        )

        detail_url = identity.normalized_detail_url
        if detail_url and not self._as_str(normalized.get("detail_page_url")):
            normalized["detail_page_url"] = detail_url
        return normalized

    def normalize_raw_document_item(self, item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        normalized_url, url_hash = self.normalize_url_and_hash(
            url=normalized.get("url"),
            normalized_url=normalized.get("normalized_url"),
        )
        normalized["normalized_url"] = normalized_url
        normalized["url_hash"] = url_hash
        normalized["content_hash"] = self.ensure_content_hash(
            content_hash=normalized.get("content_hash"),
            raw_body=normalized.get("raw_body"),
        )
        return normalized

    def normalize_attachment_item(self, item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        normalized_url, url_hash = self.normalize_url_and_hash(
            url=normalized.get("file_url"),
            normalized_url=normalized.get("file_url"),
        )
        if normalized_url:
            normalized["file_url"] = normalized_url
        normalized["url_hash"] = url_hash
        return normalized

    def _normalize_title(self, value: str | None) -> str | None:
        if not value:
            return None
        text = re.sub(r"\s+", " ", value).strip().lower()
        return text or None

    def _as_str(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None
