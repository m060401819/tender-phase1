from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.schemas.crawl_job import CrawlJobListItemResponse


class SourceSiteResponse(BaseModel):
    code: str
    name: str
    base_url: str
    description: str | None = None
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int
    default_max_pages: int


class SourceSitePatchRequest(BaseModel):
    is_active: bool | None = None
    supports_js_render: bool | None = None
    crawl_interval_minutes: int | None = Field(default=None, ge=1)
    default_max_pages: int | None = Field(default=None, ge=1)


class SourceCrawlJobTriggerRequest(BaseModel):
    max_pages: int | None = Field(default=1, ge=1)
    triggered_by: str = Field(default="api", min_length=1, max_length=64)


class SourceCrawlJobTriggerResponse(BaseModel):
    source_code: str
    job: CrawlJobListItemResponse
    return_code: int
    command: str
