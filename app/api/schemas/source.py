from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
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


class SourceSiteAdminRowActions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    manual_crawl_post_url: str = "/admin/sources/manual-crawl"
    crawl_jobs_url: str = "/admin/crawl-jobs"
    crawl_errors_url: str = "/admin/crawl-errors"
    config_url: str = "/admin/sources"


class SourceSiteAdminActiveCrawl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    job_type: str = ""
    job_type_label: str = "抓取任务"
    status: str = ""
    status_label: str = "抓取中"
    is_stale: bool = False
    stage_label: str = "抓取中"
    summary_text: str = "-"
    detail_url: str = "/admin/crawl-jobs"


class SourceSiteAdminRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = 0
    code: str = "-"
    name: str = "-"
    base_url: str = "-"
    official_url: str = "-"
    list_url: str = "-"
    is_active: bool = False
    crawl_interval_minutes: int = 60
    crawl_interval_label: str = "60 分钟"
    last_crawled_at: str = "-"
    last_new_notice_count: int = 0
    last_new_count: int = 0
    has_new_notice: bool = False
    health_status: str = "warning"
    health_badge: str = "tag-zero"
    health_status_label: str = "警告"
    last_crawl_result: str = "-"
    last_failure_summary: str = "-"
    latest_job_status_label: str = "-"
    latest_failure_reason: str = "-"
    latest_list_items_seen: int = 0
    latest_list_items_unique: int = 0
    latest_list_items_source_duplicates_skipped: int = 0
    latest_detail_pages_fetched: int = 0
    latest_source_duplicates_suppressed: int = 0
    has_source_duplicates_latest: bool = False
    recent_7d_error_count: int = 0
    default_max_pages: int = 50
    schedule_enabled: bool = False
    schedule_days: int = 1
    schedule_days_label: str = "1天一次"
    description: str = "-"
    last_scheduled_run_at: str = "-"
    next_scheduled_run_at: str = "-"
    last_schedule_status: str = "-"
    today_crawl_job_count: int = 0
    today_success_count: int = 0
    today_failed_count: int = 0
    today_new_notice_count: int = 0
    today_ops_summary: str = "成功 0 / 失败 0 / 新增 0"
    last_retry_status: str = "-"
    last_retry_job_id: int | None = None
    last_retry_label: str = "无"
    business_code: str = "-"
    crawl_supported: bool = False
    supported_job_types_label: str = "-"
    supports_backfill: bool = False
    crawl_support_message: str = ""
    has_active_crawl: bool = False
    active_crawl: SourceSiteAdminActiveCrawl = Field(default_factory=SourceSiteAdminActiveCrawl)
    actions: SourceSiteAdminRowActions = Field(default_factory=SourceSiteAdminRowActions)


class SourceSitesAdminPageViewModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    today_new_notice_count: int = 0
    recent_24h_new_notice_count: int = 0
    show_new_notice_alert: bool = False
    sources: list[SourceSiteAdminRow] = Field(default_factory=list)
    source_ops_report_url: str = "/reports/source-ops.xlsx?recent_hours=24"
    created_source_success: bool = False
    created_source_code: str = ""
    manual_crawl_error: str = ""
    manual_crawl_error_source_code: str = ""
    active_crawl_job_count: int = 0
    auto_refresh_interval_seconds: int = 5
    can_manage_sources: bool = False
