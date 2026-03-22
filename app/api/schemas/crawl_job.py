from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CrawlJobStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"


class CrawlJobType(str, Enum):
    manual = "manual"
    scheduled = "scheduled"
    backfill = "backfill"
    manual_retry = "manual_retry"


class CrawlJobOrderBy(str, Enum):
    started_at = "started_at"
    id = "id"


class CrawlJobBaseResponse(BaseModel):
    id: int
    source_site_id: int
    source_code: str
    job_type: CrawlJobType
    status: CrawlJobStatus
    retry_of_job_id: int | None = None
    retry_of_job_message: str | None = None
    retried_by_job_id: int | None = None
    retried_by_status: CrawlJobStatus | None = None
    retried_by_finished_at: datetime | None = None
    retried_by_message: str | None = None
    queued_at: datetime | None
    picked_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    timeout_at: datetime | None
    lease_expires_at: datetime | None

    pages_fetched: int
    documents_saved: int
    notices_upserted: int
    deduplicated_count: int
    error_count: int
    list_items_seen: int
    list_items_unique: int
    list_items_source_duplicates_skipped: int
    detail_pages_fetched: int
    records_inserted: int
    records_updated: int
    source_duplicates_suppressed: int

    message: str | None


class CrawlJobListItemResponse(CrawlJobBaseResponse):
    pass


class CrawlJobListResponse(BaseModel):
    items: list[CrawlJobListItemResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    order_by: CrawlJobOrderBy


class CrawlJobDetailResponse(CrawlJobBaseResponse):
    recent_crawl_error_count: int | None = None


class CrawlJobRetryRequest(BaseModel):
    max_pages: int | None = Field(default=None, ge=1)
    triggered_by: str = Field(default="api-retry", min_length=1, max_length=64)


class CrawlJobRetryResponse(BaseModel):
    original_job_id: int
    retry_job: CrawlJobListItemResponse
