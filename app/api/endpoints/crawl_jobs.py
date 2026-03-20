from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    CrawlJobDetailResponse,
    CrawlJobListItemResponse,
    CrawlJobListResponse,
    CrawlJobOrderBy,
    CrawlJobStatus,
    CrawlJobType,
)
from app.db.session import get_db
from app.repositories import CrawlJobRepository
from app.services import CrawlJobQueryService

router = APIRouter(tags=["crawl-jobs"])


@router.get("/crawl-jobs", response_model=CrawlJobListResponse)
def list_crawl_jobs(
    source_code: str | None = Query(default=None),
    status: CrawlJobStatus | None = Query(default=None),
    job_type: CrawlJobType | None = Query(default=None),
    order_by: CrawlJobOrderBy = Query(default=CrawlJobOrderBy.started_at),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CrawlJobListResponse:
    service = CrawlJobQueryService(repository=CrawlJobRepository(db))
    result = service.list_crawl_jobs(
        source_code=source_code,
        status=status.value if status else None,
        job_type=job_type.value if job_type else None,
        order_by=order_by.value,
        limit=limit,
        offset=offset,
    )

    return CrawlJobListResponse(
        items=[_to_list_item(job) for job in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        order_by=order_by,
    )


@router.get("/crawl-jobs/{job_id}", response_model=CrawlJobDetailResponse)
def get_crawl_job(job_id: int, db: Session = Depends(get_db)) -> CrawlJobDetailResponse:
    service = CrawlJobQueryService(repository=CrawlJobRepository(db))
    job = service.get_crawl_job_detail(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="crawl_job not found")

    return CrawlJobDetailResponse(
        id=job.id,
        source_site_id=job.source_site_id,
        source_code=job.source_code,
        job_type=job.job_type,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        pages_fetched=job.pages_fetched,
        documents_saved=job.documents_saved,
        notices_upserted=job.notices_upserted,
        deduplicated_count=job.deduplicated_count,
        error_count=job.error_count,
        message=job.message,
        recent_crawl_error_count=job.recent_crawl_error_count,
    )


def _to_list_item(job) -> CrawlJobListItemResponse:  # type: ignore[no-untyped-def]
    return CrawlJobListItemResponse(
        id=job.id,
        source_site_id=job.source_site_id,
        source_code=job.source_code,
        job_type=job.job_type,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        pages_fetched=job.pages_fetched,
        documents_saved=job.documents_saved,
        notices_upserted=job.notices_upserted,
        deduplicated_count=job.deduplicated_count,
        error_count=job.error_count,
        message=job.message,
    )
