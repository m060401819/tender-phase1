from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.api.schemas.notice import NoticeType


class CrawlErrorStage(str, Enum):
    fetch = "fetch"
    parse = "parse"
    persist = "persist"


class CrawlErrorRawDocumentSummaryResponse(BaseModel):
    id: int
    document_type: str
    fetched_at: datetime
    storage_uri: str


class CrawlErrorNoticeSummaryResponse(BaseModel):
    id: int
    source_code: str
    title: str
    notice_type: NoticeType
    current_version_id: int | None


class CrawlErrorNoticeVersionSummaryResponse(BaseModel):
    id: int
    notice_id: int
    version_no: int
    is_current: bool
    title: str
    notice_type: NoticeType


class CrawlErrorListItemResponse(BaseModel):
    id: int
    source_code: str
    crawl_job_id: int | None
    stage: CrawlErrorStage
    error_type: str
    message: str
    url: str | None
    created_at: datetime


class CrawlErrorListResponse(BaseModel):
    items: list[CrawlErrorListItemResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class CrawlErrorDetailResponse(BaseModel):
    id: int
    source_code: str
    crawl_job_id: int | None
    stage: CrawlErrorStage
    error_type: str
    message: str
    detail: str | None
    url: str | None
    traceback: str | None
    created_at: datetime
    raw_document: CrawlErrorRawDocumentSummaryResponse | None = None
    notice: CrawlErrorNoticeSummaryResponse | None = None
    notice_version: CrawlErrorNoticeVersionSummaryResponse | None = None
