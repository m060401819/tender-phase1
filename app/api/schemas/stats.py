from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DailyCountResponse(BaseModel):
    date: str
    count: int


class OverviewFailedJobSummaryResponse(BaseModel):
    id: int
    source_code: str
    status: str
    job_type: str
    started_at: datetime | None
    finished_at: datetime | None
    error_count: int
    message: str | None


class OverviewCrawlErrorSummaryResponse(BaseModel):
    id: int
    source_code: str
    crawl_job_id: int | None
    stage: str
    error_type: str
    message: str
    url: str | None
    created_at: datetime


class StatsOverviewResponse(BaseModel):
    source_count: int
    active_source_count: int
    crawl_job_count: int
    crawl_job_running_count: int
    notice_count: int
    raw_document_count: int
    crawl_error_count: int
    recent_7d_crawl_job_counts: list[DailyCountResponse] = Field(default_factory=list)
    recent_7d_notice_counts: list[DailyCountResponse] = Field(default_factory=list)
    recent_7d_crawl_error_counts: list[DailyCountResponse] = Field(default_factory=list)
    recent_failed_or_partial_jobs: list[OverviewFailedJobSummaryResponse] = Field(default_factory=list)
    recent_crawl_errors: list[OverviewCrawlErrorSummaryResponse] = Field(default_factory=list)
