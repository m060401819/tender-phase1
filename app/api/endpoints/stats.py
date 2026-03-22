from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import (
    DailyCountResponse,
    OverviewCrawlErrorSummaryResponse,
    OverviewFailedJobSummaryResponse,
    StatsOverviewResponse,
)
from app.db.session import get_db
from app.repositories import StatsRepository
from app.services import StatsService

router = APIRouter(tags=["stats"])


@router.get("/stats/overview", response_model=StatsOverviewResponse)
def get_stats_overview(db: Session = Depends(get_db)) -> StatsOverviewResponse:
    service = StatsService(repository=StatsRepository(db))
    item = service.get_overview()

    return StatsOverviewResponse(
        source_count=item.source_count,
        active_source_count=item.active_source_count,
        crawl_job_count=item.crawl_job_count,
        crawl_job_running_count=item.crawl_job_running_count,
        notice_count=item.notice_count,
        today_new_notice_count=item.today_new_notice_count,
        recent_24h_new_notice_count=item.recent_24h_new_notice_count,
        raw_document_count=item.raw_document_count,
        crawl_error_count=item.crawl_error_count,
        recent_7d_crawl_job_counts=[
            DailyCountResponse(date=entry.date, count=entry.count) for entry in item.recent_7d_crawl_job_counts
        ],
        recent_7d_notice_counts=[
            DailyCountResponse(date=entry.date, count=entry.count) for entry in item.recent_7d_notice_counts
        ],
        recent_7d_crawl_error_counts=[
            DailyCountResponse(date=entry.date, count=entry.count) for entry in item.recent_7d_crawl_error_counts
        ],
        recent_failed_or_partial_jobs=[
            OverviewFailedJobSummaryResponse(
                id=entry.id,
                source_code=entry.source_code,
                status=entry.status,
                job_type=entry.job_type,
                started_at=entry.started_at,
                finished_at=entry.finished_at,
                error_count=entry.error_count,
                message=entry.message,
            )
            for entry in item.recent_failed_or_partial_jobs
        ],
        recent_crawl_errors=[
            OverviewCrawlErrorSummaryResponse(
                id=entry.id,
                source_code=entry.source_code,
                crawl_job_id=entry.crawl_job_id,
                stage=entry.stage,
                error_type=entry.error_type,
                message=entry.message,
                url=entry.url,
                created_at=entry.created_at,
            )
            for entry in item.recent_crawl_errors
        ],
    )
