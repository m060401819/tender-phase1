"""Application service layer."""

from app.services.crawl_job_service import (
    CRAWL_JOB_FINAL_STATUSES,
    CRAWL_JOB_STATUSES,
    CRAWL_JOB_TYPES,
    CrawlJobService,
    CrawlJobSnapshot,
)
from app.services.crawl_job_query_service import CrawlJobQueryService
from app.services.notice_query_service import NoticeQueryService
from app.services.raw_document_query_service import RawDocumentQueryService
from app.services.crawl_error_query_service import CrawlErrorQueryService
from app.services.stats_service import StatsService
from app.services.source_crawl_trigger_service import (
    CrawlCommandRunner,
    SourceCrawlTriggerResult,
    SourceCrawlTriggerService,
    SubprocessCrawlCommandRunner,
)
from app.services.source_schedule_service import (
    SCHEDULE_DAY_OPTIONS,
    SourceScheduleRuntime,
    calculate_next_scheduled_run,
    get_source_schedule_runtime,
    initialize_source_schedule_runtime,
    shutdown_source_schedule_runtime,
    sync_source_schedule,
)
from app.services.source_health_service import (
    HEALTH_STATUS_LABELS,
    JOB_STATUS_LABELS,
    SourceHealthService,
    SourceHealthSummary,
)
from app.services.health_rule_service import (
    DEFAULT_HEALTH_RULES,
    HealthRuleService,
    HealthRuleSnapshot,
)
from app.services.source_site_service import SourceSiteService
from app.services.source_ops_service import SourceOpsService, SourceOpsSummary
from app.services.demo_bootstrap_service import DemoSourceSeed, bootstrap_demo_sources
from app.services.source_adapter_registry import (
    SourceAdapterMeta,
    get_source_adapter,
    is_source_integrated,
    list_integrated_source_codes,
    normalize_source_code,
    resolve_spider_name,
    supports_job_type,
)

__all__ = [
    "CRAWL_JOB_TYPES",
    "CRAWL_JOB_STATUSES",
    "CRAWL_JOB_FINAL_STATUSES",
    "CrawlJobSnapshot",
    "CrawlJobService",
    "CrawlJobQueryService",
    "NoticeQueryService",
    "RawDocumentQueryService",
    "CrawlErrorQueryService",
    "StatsService",
    "SourceSiteService",
    "CrawlCommandRunner",
    "SubprocessCrawlCommandRunner",
    "SourceCrawlTriggerResult",
    "SourceCrawlTriggerService",
    "SCHEDULE_DAY_OPTIONS",
    "SourceScheduleRuntime",
    "calculate_next_scheduled_run",
    "get_source_schedule_runtime",
    "initialize_source_schedule_runtime",
    "shutdown_source_schedule_runtime",
    "sync_source_schedule",
    "HEALTH_STATUS_LABELS",
    "JOB_STATUS_LABELS",
    "SourceHealthSummary",
    "SourceHealthService",
    "DEFAULT_HEALTH_RULES",
    "HealthRuleSnapshot",
    "HealthRuleService",
    "SourceOpsSummary",
    "SourceOpsService",
    "DemoSourceSeed",
    "bootstrap_demo_sources",
    "SourceAdapterMeta",
    "normalize_source_code",
    "get_source_adapter",
    "is_source_integrated",
    "resolve_spider_name",
    "supports_job_type",
    "list_integrated_source_codes",
]
