from __future__ import annotations

from datetime import datetime

from app.repositories import (
    CrawlJobListResult,
    CrawlJobOrderBy,
    CrawlJobQueryFilters,
    CrawlJobRecord,
    CrawlJobRepository,
)
from .crawl_job_service import reconcile_expired_jobs_in_session


class CrawlJobQueryService:
    """Service layer for crawl_job query APIs."""

    def __init__(self, repository: CrawlJobRepository) -> None:
        self.repository = repository

    def list_crawl_jobs(
        self,
        *,
        source_code: str | None,
        status: str | None,
        job_type: str | None,
        status_in: tuple[str, ...] | None,
        started_from: datetime | None,
        order_by: CrawlJobOrderBy,
        limit: int,
        offset: int,
    ) -> CrawlJobListResult:
        expired_jobs = reconcile_expired_jobs_in_session(self.repository.session)
        if expired_jobs:
            self.repository.session.commit()
        return self.repository.list_jobs(
            filters=CrawlJobQueryFilters(
                source_code=source_code,
                status=status,
                job_type=job_type,
                status_in=status_in,
                started_from=started_from,
            ),
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def get_crawl_job_detail(self, job_id: int) -> CrawlJobRecord | None:
        expired_jobs = reconcile_expired_jobs_in_session(self.repository.session)
        if expired_jobs:
            self.repository.session.commit()
        return self.repository.get_job_detail(job_id)
