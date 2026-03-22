from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl
from pydantic import field_validator, model_validator

from app.api.schemas.crawl_job import CrawlJobListItemResponse

SCHEDULE_DAY_OPTIONS = {1, 2, 3, 7}


class SourceSiteResponse(BaseModel):
    code: str
    name: str
    base_url: str
    official_url: str
    list_url: str
    description: str | None = None
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int
    default_max_pages: int


class SourceSitePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    official_url: HttpUrl | None = None
    list_url: HttpUrl | None = None
    description: str | None = None
    is_active: bool | None = None
    supports_js_render: bool | None = None
    crawl_interval_minutes: int | None = Field(default=None, ge=1)
    default_max_pages: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def strip_patch_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class SourceSiteCreateRequest(BaseModel):
    source_code: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=255)
    official_url: HttpUrl
    list_url: HttpUrl
    remark: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    schedule_enabled: bool = False
    schedule_days: int = 1
    crawl_interval_minutes: int = Field(default=1440, ge=1)
    default_max_pages: int | None = Field(default=None, ge=1)

    @field_validator("source_code", "source_name")
    @classmethod
    def strip_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("schedule_days")
    @classmethod
    def validate_create_schedule_days(cls, value: int) -> int:
        if value not in SCHEDULE_DAY_OPTIONS:
            raise ValueError("schedule_days must be one of 1, 2, 3, 7")
        return value


class SourceCrawlJobTriggerRequest(BaseModel):
    job_type: Literal["manual", "backfill"] = "manual"
    max_pages: int | None = Field(default=None, ge=1)
    backfill_year: int | None = Field(default=None, ge=2000, le=2100)
    triggered_by: str = Field(default="api", min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_backfill_year(self) -> "SourceCrawlJobTriggerRequest":
        if self.job_type == "backfill" and self.backfill_year is None:
            raise ValueError("backfill_year is required when job_type=backfill")
        return self


class SourceCrawlJobTriggerResponse(BaseModel):
    source_code: str
    job: CrawlJobListItemResponse
    return_code: int
    command: str


class SourceScheduleResponse(BaseModel):
    source_code: str
    schedule_enabled: bool
    schedule_days: int
    next_scheduled_run_at: datetime | None = None
    last_scheduled_run_at: datetime | None = None
    last_schedule_status: str | None = None


class SourceSchedulePatchRequest(BaseModel):
    schedule_enabled: bool | None = None
    schedule_days: int | None = None

    @field_validator("schedule_days")
    @classmethod
    def validate_schedule_days(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value not in SCHEDULE_DAY_OPTIONS:
            raise ValueError("schedule_days must be one of 1, 2, 3, 7")
        return value


class SourceHealthResponse(BaseModel):
    source_code: str
    health_status: str
    health_status_label: str
    latest_job_id: int | None = None
    latest_job_status: str | None = None
    latest_job_status_label: str
    latest_job_started_at: datetime | None = None
    latest_notices_upserted: int
    latest_error_count: int
    recent_7d_job_count: int
    recent_7d_failed_count: int
    recent_7d_error_count: int
    consecutive_failed: bool
    latest_failure_reason: str
