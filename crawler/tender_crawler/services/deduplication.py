from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from dataclasses import dataclass
from datetime import datetime, timezone
import unicodedata
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from tender_crawler.utils import normalize_url, sha256_text

NOTICE_TYPES = {"announcement", "change", "result"}
_IRRELEVANT_QUERY_PARAM_NAMES = {
    "_",
    "_t",
    "_ts",
    "from",
    "rand",
    "random",
    "ref",
    "referer",
    "sessionid",
    "sid",
    "spm",
    "timestamp",
    "track",
    "tracking",
}
_IRRELEVANT_QUERY_PARAM_PREFIXES = ("utm_",)
_PUNCT_TRANSLATIONS = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "、": ",",
        "－": "-",
    }
)
_DETAIL_LOCATOR_KEYS = (
    "guid",
    "detail_id",
    "detailid",
    "id",
    "notice_id",
    "noticeid",
    "article_id",
    "articleid",
)
_BUDGET_BUCKET_GRANULARITY = Decimal("1000")


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

    def normalize_text(self, value: object, *, lowercase: bool = False) -> str | None:
        text = self._as_str(value)
        if text is None:
            return None
        normalized = unicodedata.normalize("NFKC", text)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return None
        return normalized.lower() if lowercase else normalized

    def normalize_title(self, value: object) -> str | None:
        text = self.normalize_text(value, lowercase=True)
        if text is None:
            return None
        text = text.translate(_PUNCT_TRANSLATIONS)
        text = re.sub(r"\s+", "", text)
        return text or None

    def normalize_region(self, value: object) -> str | None:
        return self.normalize_text(value, lowercase=True)

    def normalize_purchaser_or_publisher(self, value: object) -> str | None:
        text = self.normalize_text(value, lowercase=True)
        if text is None:
            return None
        text = text.translate(_PUNCT_TRANSLATIONS)
        text = re.sub(r"\s+", "", text)
        return text or None

    def normalize_budget_bucket(self, value: object) -> str | None:
        if value is None:
            return None

        normalized = self.normalize_text(value)
        if normalized is None:
            return None

        unit_multiplier = Decimal("1")
        if "万元" in normalized or "万" in normalized:
            unit_multiplier = Decimal("10000")

        number_match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", normalized.replace(",", ""))
        if number_match is None:
            return None

        try:
            amount = Decimal(number_match.group(0)) * unit_multiplier
        except (InvalidOperation, ValueError):
            return None

        bucket_steps = (amount / _BUDGET_BUCKET_GRANULARITY).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        bucket_value = (bucket_steps * _BUDGET_BUCKET_GRANULARITY).quantize(Decimal("1"))
        return str(int(bucket_value))

    def normalize_detail_url(self, value: object) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        cleaned = self._drop_irrelevant_query_params(text)
        return normalize_url(cleaned)

    def normalize_published_date(self, value: object) -> str | None:
        dt = self.parse_datetime_like(value)
        if dt is None:
            text = self.normalize_text(value)
            if text is None:
                return None
            date_match = re.search(r"([0-9]{4})[-/年]([0-9]{1,2})[-/月]([0-9]{1,2})", text)
            if date_match is None:
                return None
            year, month, day = [int(part) for part in date_match.groups()]
            dt = datetime(year, month, day, tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date().isoformat()

    def parse_datetime_like(self, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        text = self.normalize_text(value)
        if not text:
            return None

        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y%m%d",
            "%Y年%m月%d日 %H点%M分",
            "%Y年%m月%d日%H点%M分",
            "%Y年%m月%d日",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def build_source_list_item_fingerprint(
        self,
        *,
        source_code: object,
        title: object,
        detail_url: object,
        published_at: object,
        region: object = None,
        notice_type: object = None,
        include_detail_locator: bool = True,
    ) -> str:
        normalized_detail = (
            self.normalize_detail_url(detail_url)
            if include_detail_locator
            else None
        )
        seed = "|".join(
            [
                self._stable_seed_text(self._as_str(source_code)),
                self._stable_seed_text(self.normalize_title(title)),
                self._stable_seed_text(normalized_detail),
                self._stable_seed_text(self.normalize_published_date(published_at)),
                self._stable_seed_text(self.normalize_notice_type(notice_type)),
                self._stable_seed_text(self.normalize_region(region)),
            ]
        )
        return sha256_text(seed)

    def build_source_duplicate_key(
        self,
        *,
        source_code: object,
        title: object,
        detail_url: object,
        published_at: object,
        issuer: object = None,
        purchaser: object = None,
        publisher: object = None,
        budget_amount: object = None,
        detail_id: object | None = None,
        notice_type: object = None,
        region: object = None,
    ) -> str:
        normalized_source = self.normalize_text(source_code, lowercase=True)
        normalized_notice_type = self.normalize_notice_type(notice_type)
        detail_locator = self.extract_detail_locator(detail_url=detail_url, detail_id=detail_id)
        if detail_locator:
            return sha256_text(
                "|".join(
                    [
                        self._stable_seed_text(normalized_source),
                        self._stable_seed_text(normalized_notice_type),
                        self._stable_seed_text(detail_locator),
                    ]
                )
            )

        return self.build_persistence_dedup_key(
            title=title,
            published_at=published_at,
            purchaser=purchaser,
            publisher=publisher or issuer,
            budget_amount=budget_amount,
            region=region,
        )

    def extract_detail_locator(self, *, detail_url: object, detail_id: object | None = None) -> str | None:
        explicit_detail_id = self._as_str(detail_id)
        if explicit_detail_id:
            normalized_detail_id = self.normalize_text(explicit_detail_id, lowercase=True)
            if normalized_detail_id:
                return normalized_detail_id

        normalized_detail_url = self.normalize_detail_url(detail_url)
        if normalized_detail_url is None:
            return None

        query = parse_qs(urlsplit(normalized_detail_url).query)
        for key in _DETAIL_LOCATOR_KEYS:
            values = query.get(key) or query.get(key.upper())
            if not values:
                continue
            value = self.normalize_text(values[0], lowercase=True)
            if value:
                return value

        return normalized_detail_url

    def build_notice_dedup_key(
        self,
        *,
        title: object,
        published_at: object,
        purchaser: object = None,
        publisher: object = None,
        budget_amount: object = None,
        region: object = None,
        detail_url: object = None,
        detail_id: object | None = None,
        include_detail_locator: bool = True,
    ) -> str:
        normalized_title = self.normalize_title(title)
        normalized_published_date = self.normalize_published_date(published_at)
        normalized_purchaser_or_publisher = (
            self.normalize_purchaser_or_publisher(purchaser)
            or self.normalize_purchaser_or_publisher(publisher)
        )
        normalized_budget_bucket = self.normalize_budget_bucket(budget_amount)
        normalized_region = self.normalize_region(region)
        normalized_detail_locator = (
            self.extract_detail_locator(
                detail_url=detail_url,
                detail_id=detail_id,
            )
            if include_detail_locator
            else None
        )
        seed = "|".join(
            [
                self._stable_seed_text(normalized_title),
                self._stable_seed_text(normalized_published_date),
                self._stable_seed_text(normalized_purchaser_or_publisher),
                self._stable_seed_text(normalized_budget_bucket),
                self._stable_seed_text(normalized_region),
                self._stable_seed_text(normalized_detail_locator),
            ]
        )
        return sha256_text(seed)

    def build_persistence_dedup_key(
        self,
        *,
        title: object,
        published_at: object,
        purchaser: object = None,
        publisher: object = None,
        budget_amount: object = None,
        region: object = None,
        detail_url: object = None,
        detail_id: object | None = None,
    ) -> str:
        normalized_purchaser_or_publisher = (
            self.normalize_purchaser_or_publisher(purchaser)
            or self.normalize_purchaser_or_publisher(publisher)
        )
        normalized_budget_bucket = self.normalize_budget_bucket(budget_amount)
        normalized_region = self.normalize_region(region)
        signal_count = sum(
            1
            for value in (normalized_purchaser_or_publisher, normalized_budget_bucket, normalized_region)
            if value
        )
        include_detail_locator = signal_count < 2
        return self.build_notice_dedup_key(
            title=title,
            published_at=published_at,
            purchaser=purchaser,
            publisher=publisher,
            budget_amount=budget_amount,
            region=region,
            detail_url=detail_url,
            detail_id=detail_id,
            include_detail_locator=include_detail_locator,
        )

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
        title = self.normalize_title(item.get("title"))

        normalized_detail_url = None
        if detail_url:
            normalized_detail_url = self.normalize_detail_url(detail_url)

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
        dedup_key = self._as_str(normalized.get("dedup_key")) or self.build_persistence_dedup_key(
            title=normalized.get("title"),
            published_at=normalized.get("published_at"),
            purchaser=normalized.get("purchaser"),
            publisher=normalized.get("issuer") or normalized.get("publisher"),
            budget_amount=normalized.get("budget_amount"),
            region=normalized.get("region"),
            detail_url=normalized.get("detail_page_url") or normalized.get("source_url") or normalized.get("url"),
            detail_id=normalized.get("external_id") or normalized.get("notice_external_id"),
        )
        dedup_hash = self._as_str(normalized.get("dedup_hash") or normalized.get("notice_dedup_hash"))
        normalized["dedup_key"] = dedup_key
        normalized["dedup_hash"] = dedup_hash or identity.dedup_hash
        normalized["notice_dedup_hash"] = dedup_hash or identity.dedup_hash
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

        normalized["source_duplicate_key"] = self._as_str(normalized.get("source_duplicate_key")) or self.build_source_duplicate_key(
            source_code=normalized.get("source_code"),
            title=normalized.get("title"),
            detail_url=normalized.get("detail_page_url") or normalized.get("source_url") or normalized.get("url"),
            published_at=normalized.get("published_at"),
            issuer=normalized.get("issuer"),
            purchaser=normalized.get("purchaser"),
            publisher=normalized.get("publisher"),
            budget_amount=normalized.get("budget_amount"),
            detail_id=normalized.get("external_id") or normalized.get("notice_external_id"),
            notice_type=normalized.get("notice_type"),
            region=normalized.get("region"),
        )
        return normalized

    def normalize_raw_document_item(self, item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        normalized_url = self.normalize_detail_url(
            normalized.get("normalized_url") or normalized.get("url")
        )
        url_hash = sha256_text(normalized_url) if normalized_url else None
        normalized["normalized_url"] = normalized_url
        normalized["url_hash"] = url_hash
        normalized["content_hash"] = self.ensure_content_hash(
            content_hash=normalized.get("content_hash"),
            raw_body=normalized.get("raw_body"),
        )
        source_duplicate_key = normalized.get("source_duplicate_key")
        if not self._as_str(source_duplicate_key):
            source_duplicate_key = self.build_source_duplicate_key(
                source_code=normalized.get("source_code"),
                title=normalized.get("title"),
                detail_url=normalized.get("url") or normalized.get("normalized_url"),
                published_at=(normalized.get("extra_meta") or {}).get("published_at")
                if isinstance(normalized.get("extra_meta"), dict)
                else None,
                issuer=(normalized.get("extra_meta") or {}).get("issuer")
                if isinstance(normalized.get("extra_meta"), dict)
                else None,
                notice_type=(normalized.get("extra_meta") or {}).get("notice_type")
                if isinstance(normalized.get("extra_meta"), dict)
                else None,
                region=(normalized.get("extra_meta") or {}).get("region")
                if isinstance(normalized.get("extra_meta"), dict)
                else None,
            )
        normalized["source_duplicate_key"] = source_duplicate_key
        return normalized

    def normalize_attachment_item(self, item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        normalized_url = self.normalize_detail_url(normalized.get("file_url"))
        url_hash = sha256_text(normalized_url) if normalized_url else None
        if normalized_url:
            normalized["file_url"] = normalized_url
        normalized["url_hash"] = url_hash
        return normalized

    def _drop_irrelevant_query_params(self, url: str) -> str:
        split = urlsplit(url.strip())
        filtered_query = []
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            lowered = key.strip().lower()
            if lowered in _IRRELEVANT_QUERY_PARAM_NAMES:
                continue
            if any(lowered.startswith(prefix) for prefix in _IRRELEVANT_QUERY_PARAM_PREFIXES):
                continue
            filtered_query.append((key, value))
        normalized_query = urlencode(sorted(filtered_query))
        return urlunsplit((split.scheme, split.netloc, split.path, normalized_query, ""))

    def _stable_seed_text(self, value: str | None) -> str:
        return value if value else "-"

    def _as_str(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None
