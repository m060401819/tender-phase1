from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    CrawlJobDetailResponse,
    CrawlJobListItemResponse,
    CrawlJobListResponse,
    CrawlJobOrderBy,
    CrawlJobRetryRequest,
    CrawlJobRetryResponse,
    CrawlJobStatus,
    CrawlJobType,
)
from app.api.endpoints.sources import get_source_crawl_trigger_service
from app.core.auth import require_ops_user
from app.db.session import get_db
from app.models import SourceSite
from app.repositories import CrawlJobRecord
from app.repositories import CrawlJobRepository
from app.services import (
    CrawlJobQueryService,
    CrawlJobRetryConflictError,
    CrawlJobRetryNotFoundError,
    CrawlJobRetryValidationError,
    SourceActiveCrawlJobConflictError,
    SourceCrawlTriggerService,
)

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
        status_in=None,
        started_from=None,
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
        job_type=_to_crawl_job_type(job.job_type),
        status=_to_crawl_job_status(job.status),
        retry_of_job_id=job.retry_of_job_id,
        retry_of_job_message=job.retry_of_job_message,
        retried_by_job_id=job.retried_by_job_id,
        retried_by_status=_to_optional_crawl_job_status(job.retried_by_status),
        retried_by_finished_at=job.retried_by_finished_at,
        retried_by_message=job.retried_by_message,
        queued_at=job.queued_at,
        picked_at=job.picked_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
        timeout_at=job.timeout_at,
        lease_expires_at=job.lease_expires_at,
        pages_fetched=job.pages_fetched,
        documents_saved=job.documents_saved,
        notices_upserted=job.notices_upserted,
        deduplicated_count=job.deduplicated_count,
        error_count=job.error_count,
        list_items_seen=job.list_items_seen,
        list_items_unique=job.list_items_unique,
        list_items_source_duplicates_skipped=job.list_items_source_duplicates_skipped,
        detail_pages_fetched=job.detail_pages_fetched,
        records_inserted=job.records_inserted,
        records_updated=job.records_updated,
        source_duplicates_suppressed=job.source_duplicates_suppressed,
        job_params_json=job.job_params_json,
        runtime_stats_json=job.runtime_stats_json,
        failure_reason=job.failure_reason,
        message=job.message,
        recent_crawl_error_count=job.recent_crawl_error_count,
    )


@router.post(
    "/crawl-jobs/{job_id}/retry",
    response_model=CrawlJobRetryResponse,
    status_code=201,
    dependencies=[Depends(require_ops_user)],
)
def retry_crawl_job(
    job_id: int,
    payload: CrawlJobRetryRequest,
    db: Session = Depends(get_db),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
) -> CrawlJobRetryResponse:
    try:
        result = trigger_service.queue_retry_crawl_for_job(
            crawl_job_id=job_id,
            max_pages=payload.max_pages,
            triggered_by=payload.triggered_by,
        )
    except CrawlJobRetryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CrawlJobRetryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CrawlJobRetryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SourceActiveCrawlJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    retry_job = result.job
    source = db.get(SourceSite, retry_job.source_site_id)
    if source is None:
        raise HTTPException(status_code=500, detail="retry job source missing")

    return CrawlJobRetryResponse(
        original_job_id=job_id,
        retry_job=CrawlJobListItemResponse(
            id=retry_job.id,
            source_site_id=retry_job.source_site_id,
            source_code=source.code,
            job_type=_to_crawl_job_type(retry_job.job_type),
            status=_to_crawl_job_status(retry_job.status),
            retry_of_job_id=retry_job.retry_of_job_id,
            retry_of_job_message=None,
            retried_by_job_id=None,
            retried_by_status=None,
            retried_by_finished_at=None,
            retried_by_message=None,
            queued_at=retry_job.queued_at,
            picked_at=retry_job.picked_at,
            started_at=retry_job.started_at,
            finished_at=retry_job.finished_at,
            heartbeat_at=retry_job.heartbeat_at,
            timeout_at=retry_job.timeout_at,
            lease_expires_at=retry_job.lease_expires_at,
            pages_fetched=retry_job.pages_fetched,
            documents_saved=retry_job.documents_saved,
            notices_upserted=retry_job.notices_upserted,
            deduplicated_count=retry_job.deduplicated_count,
            error_count=retry_job.error_count,
            list_items_seen=retry_job.list_items_seen,
            list_items_unique=retry_job.list_items_unique,
            list_items_source_duplicates_skipped=retry_job.list_items_source_duplicates_skipped,
            detail_pages_fetched=retry_job.detail_pages_fetched,
            records_inserted=retry_job.records_inserted,
            records_updated=retry_job.records_updated,
            source_duplicates_suppressed=retry_job.source_duplicates_suppressed,
            job_params_json=retry_job.job_params_json,
            runtime_stats_json=retry_job.runtime_stats_json,
            failure_reason=retry_job.failure_reason,
            message=retry_job.message,
        ),
    )


def _to_list_item(job: CrawlJobRecord) -> CrawlJobListItemResponse:
    return CrawlJobListItemResponse(
        id=job.id,
        source_site_id=job.source_site_id,
        source_code=job.source_code,
        job_type=_to_crawl_job_type(job.job_type),
        status=_to_crawl_job_status(job.status),
        retry_of_job_id=job.retry_of_job_id,
        retry_of_job_message=job.retry_of_job_message,
        retried_by_job_id=job.retried_by_job_id,
        retried_by_status=_to_optional_crawl_job_status(job.retried_by_status),
        retried_by_finished_at=job.retried_by_finished_at,
        retried_by_message=job.retried_by_message,
        queued_at=job.queued_at,
        picked_at=job.picked_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
        timeout_at=job.timeout_at,
        lease_expires_at=job.lease_expires_at,
        pages_fetched=job.pages_fetched,
        documents_saved=job.documents_saved,
        notices_upserted=job.notices_upserted,
        deduplicated_count=job.deduplicated_count,
        error_count=job.error_count,
        list_items_seen=job.list_items_seen,
        list_items_unique=job.list_items_unique,
        list_items_source_duplicates_skipped=job.list_items_source_duplicates_skipped,
        detail_pages_fetched=job.detail_pages_fetched,
        records_inserted=job.records_inserted,
        records_updated=job.records_updated,
        source_duplicates_suppressed=job.source_duplicates_suppressed,
        job_params_json=job.job_params_json,
        runtime_stats_json=job.runtime_stats_json,
        failure_reason=job.failure_reason,
        message=job.message,
    )


def _to_crawl_job_type(value: str) -> CrawlJobType:
    return CrawlJobType(value)


def _to_crawl_job_status(value: str) -> CrawlJobStatus:
    return CrawlJobStatus(value)


def _to_optional_crawl_job_status(value: str | None) -> CrawlJobStatus | None:
    if value is None:
        return None
    return CrawlJobStatus(value)
