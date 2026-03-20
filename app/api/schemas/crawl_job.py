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


class CrawlJobOrderBy(str, Enum):
    started_at = "started_at"
    id = "id"


class CrawlJobBaseResponse(BaseModel):
    id: int
    source_site_id: int
    source_code: str
    job_type: CrawlJobType
    status: CrawlJobStatus
    started_at: datetime | None
    finished_at: datetime | None

    pages_fetched: int
    documents_saved: int
    notices_upserted: int
    deduplicated_count: int
    error_count: int

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
