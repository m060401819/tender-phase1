from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.notice import NoticeType


class RawDocumentNoticeVersionSummaryResponse(BaseModel):
    id: int
    notice_id: int
    version_no: int
    is_current: bool
    title: str
    notice_type: NoticeType


class RawDocumentNoticeSummaryResponse(BaseModel):
    id: int
    source_code: str
    title: str
    notice_type: NoticeType
    published_at: datetime | None
    current_version_id: int | None


class RawDocumentDetailResponse(BaseModel):
    id: int
    source_code: str
    crawl_job_id: int | None
    url: str
    normalized_url: str
    document_type: str
    fetched_at: datetime
    storage_uri: str
    mime_type: str | None
    title: str | None
    content_hash: str | None
    notice_version: RawDocumentNoticeVersionSummaryResponse | None = None
    tender_notice: RawDocumentNoticeSummaryResponse | None = None


class RawDocumentListItemResponse(BaseModel):
    id: int
    source_code: str
    crawl_job_id: int | None
    url: str
    normalized_url: str
    document_type: str
    fetched_at: datetime
    storage_uri: str
    mime_type: str | None
    title: str | None
    content_hash: str | None


class RawDocumentListResponse(BaseModel):
    items: list[RawDocumentListItemResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
