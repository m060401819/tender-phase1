from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import mimetypes
from typing import Any
from urllib.parse import urljoin, urlparse, unquote

from scrapy.http import TextResponse

from tender_crawler.utils import normalize_url


@dataclass(slots=True)
class ParsedAttachment:
    file_name: str
    file_url: str
    attachment_type: str = "notice_file"
    mime_type: str | None = None
    file_hash: str | None = None
    file_size_bytes: int | None = None
    storage_uri: str | None = None


@dataclass(slots=True)
class ParsedNotice:
    title: str
    notice_type: str = "announcement"
    external_id: str | None = None
    project_code: str | None = None
    issuer: str | None = None
    region: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    budget_amount: Decimal | None = None
    budget_currency: str = "CNY"
    summary: str | None = None
    content_text: str | None = None
    source_site_name: str | None = None
    source_site_url: str | None = None
    list_page_url: str | None = None
    detail_page_url: str | None = None
    change_summary: str | None = None
    structured_data: dict[str, Any] = field(default_factory=dict)
    attachments: list[ParsedAttachment] = field(default_factory=list)


class BaseNoticeParser:
    """Base parser that converts raw HTML response to normalized notice payload."""

    def parse(self, response: TextResponse) -> ParsedNotice:
        title = self._extract_title(response)
        summary = self._extract_summary(response)
        attachments = self.extract_attachments(response)

        return ParsedNotice(
            title=title,
            notice_type="announcement",
            summary=summary,
            structured_data={
                "source_url": response.url,
                "parser": self.__class__.__name__,
            },
            attachments=attachments,
        )

    def _extract_title(self, response: TextResponse) -> str:
        title = response.css("title::text").get(default="").strip()
        return title or response.url

    def _extract_summary(self, response: TextResponse) -> str | None:
        text = response.css("p::text").get(default="").strip()
        return text or None

    def extract_attachments(self, response: TextResponse) -> list[ParsedAttachment]:
        attachments: list[ParsedAttachment] = []
        seen_urls: set[str] = set()

        for href in response.css("a::attr(href)").getall():
            candidate = href.strip()
            if not candidate:
                continue

            lowered = candidate.lower()
            if not lowered.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")):
                continue

            parsed = self.build_attachment(
                file_url=candidate,
                base_url=response.url,
                link_text=None,
                attachment_type="notice_file",
            )
            if parsed is None:
                continue

            normalized_url = normalize_url(parsed.file_url)
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            attachments.append(parsed)

        return attachments

    def build_attachment(
        self,
        *,
        file_url: str,
        base_url: str,
        link_text: str | None,
        attachment_type: str = "notice_file",
        mime_type: str | None = None,
    ) -> ParsedAttachment | None:
        raw_url = (file_url or "").strip()
        if not raw_url:
            return None

        absolute_url = urljoin(base_url, raw_url)
        normalized_url = normalize_url(absolute_url)
        name = self._infer_file_name(absolute_url=absolute_url, link_text=link_text)
        resolved_mime = mime_type or self._infer_mime_type(file_name=name, file_url=normalized_url)
        return ParsedAttachment(
            file_name=name,
            file_url=normalized_url,
            attachment_type=attachment_type,
            mime_type=resolved_mime,
        )

    def _infer_file_name(self, *, absolute_url: str, link_text: str | None) -> str:
        parsed = urlparse(absolute_url)
        candidate = unquote(parsed.path.rsplit("/", maxsplit=1)[-1])
        candidate = candidate.strip()
        if candidate:
            return candidate

        text = (link_text or "").strip()
        if text:
            return text
        return "attachment"

    def _infer_mime_type(self, *, file_name: str, file_url: str) -> str | None:
        mime_type, _ = mimetypes.guess_type(file_name)
        if mime_type:
            return mime_type
        mime_type, _ = mimetypes.guess_type(file_url)
        return mime_type
