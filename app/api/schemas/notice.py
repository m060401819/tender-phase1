from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class NoticeType(str, Enum):
    announcement = "announcement"
    change = "change"
    result = "result"


class NoticeListItemResponse(BaseModel):
    id: int
    source_code: str
    title: str
    notice_type: NoticeType
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    current_version_id: int | None


class NoticeListResponse(BaseModel):
    items: list[NoticeListItemResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class NoticeSourceResponse(BaseModel):
    id: int
    code: str
    name: str
    base_url: str
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int


class RawDocumentSummaryResponse(BaseModel):
    id: int
    document_type: str
    fetched_at: datetime
    storage_uri: str


class NoticeVersionResponse(BaseModel):
    id: int
    notice_id: int
    raw_document_id: int | None
    version_no: int
    is_current: bool
    content_hash: str
    title: str
    notice_type: NoticeType
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    budget_currency: str
    change_summary: str | None
    structured_data: dict | None
    raw_document: RawDocumentSummaryResponse | None = None


class NoticeAttachmentResponse(BaseModel):
    id: int
    notice_version_id: int | None
    file_name: str
    file_url: str
    attachment_type: str
    mime_type: str | None
    file_size_bytes: int | None
    storage_uri: str | None


class NoticeDetailResponse(BaseModel):
    id: int
    source_site_id: int
    source_code: str
    external_id: str | None
    project_code: str | None
    title: str
    notice_type: NoticeType
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    budget_currency: str
    summary: str | None
    first_published_at: datetime | None
    latest_published_at: datetime | None
    current_version_id: int | None

    source: NoticeSourceResponse
    current_version: NoticeVersionResponse | None
    versions: list[NoticeVersionResponse] = Field(default_factory=list)
    attachments: list[NoticeAttachmentResponse] = Field(default_factory=list)
