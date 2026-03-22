from __future__ import annotations

from app.repositories import (
    CrawlErrorDetailRecord,
    CrawlErrorListResult,
    CrawlErrorQueryFilters,
    CrawlErrorRepository,
    CrawlErrorSourceSummaryRecord,
)


class CrawlErrorQueryService:
    """Service layer for crawl_error list/detail APIs."""

    def __init__(self, repository: CrawlErrorRepository) -> None:
        self.repository = repository

    def list_crawl_errors(
        self,
        *,
        source_code: str | None,
        stage: str | None,
        crawl_job_id: int | None,
        error_type: str | None,
        limit: int,
        offset: int,
    ) -> CrawlErrorListResult:
        return self.repository.list_errors(
            filters=CrawlErrorQueryFilters(
                source_code=source_code,
                stage=stage,
                crawl_job_id=crawl_job_id,
                error_type=error_type,
            ),
            limit=limit,
            offset=offset,
        )

    def get_crawl_error_detail(self, error_id: int) -> CrawlErrorDetailRecord | None:
        return self.repository.get_error_detail(error_id)

    def list_recent_source_summaries(
        self,
        *,
        source_code: str | None,
        stage: str | None,
        crawl_job_id: int | None,
        error_type: str | None,
        recent_days: int = 7,
        limit: int = 20,
    ) -> list[CrawlErrorSourceSummaryRecord]:
        return self.repository.list_recent_source_summaries(
            filters=CrawlErrorQueryFilters(
                source_code=source_code,
                stage=stage,
                crawl_job_id=crawl_job_id,
                error_type=error_type,
            ),
            recent_days=recent_days,
            limit=limit,
        )
