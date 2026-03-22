from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
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
from app.db.session import get_db
from app.models import CrawlJob, SourceSite
from app.repositories import CrawlJobRepository
from app.services import CrawlJobQueryService, SourceCrawlTriggerService

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
        job_type=job.job_type,
        status=job.status,
        retry_of_job_id=job.retry_of_job_id,
        retry_of_job_message=job.retry_of_job_message,
        retried_by_job_id=job.retried_by_job_id,
        retried_by_status=job.retried_by_status,
        retried_by_finished_at=job.retried_by_finished_at,
        retried_by_message=job.retried_by_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
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
        message=job.message,
        recent_crawl_error_count=job.recent_crawl_error_count,
    )


@router.post("/crawl-jobs/{job_id}/retry", response_model=CrawlJobRetryResponse, status_code=201)
def retry_crawl_job(
    job_id: int,
    payload: CrawlJobRetryRequest,
    db: Session = Depends(get_db),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
) -> CrawlJobRetryResponse:
    job = db.get(CrawlJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="crawl_job not found")

    if job.status not in {"failed", "partial"}:
        raise HTTPException(status_code=400, detail="only failed or partial job can be retried")
    if job.retry_of_job_id is not None:
        raise HTTPException(status_code=400, detail="retry job cannot be retried again")

    existing_retry = db.scalar(select(CrawlJob.id).where(CrawlJob.retry_of_job_id == job_id))
    if existing_retry is not None:
        raise HTTPException(status_code=400, detail="job already retried")

    source = db.get(SourceSite, job.source_site_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    message_fields = _parse_message_key_values(job.message)
    inherited_backfill_year = _as_int(message_fields.get("backfill_year"))
    inherited_max_pages = _as_int(message_fields.get("max_pages"))
    max_pages = payload.max_pages if payload.max_pages is not None else inherited_max_pages or int(source.default_max_pages)
    result = trigger_service.trigger_retry_crawl(
        source=source,
        retry_of_job_id=job_id,
        max_pages=max_pages,
        backfill_year=inherited_backfill_year,
        triggered_by=payload.triggered_by,
    )
    retry_job = result.job

    return CrawlJobRetryResponse(
        original_job_id=job_id,
        retry_job=CrawlJobListItemResponse(
            id=retry_job.id,
            source_site_id=retry_job.source_site_id,
            source_code=source.code,
            job_type=retry_job.job_type,
            status=retry_job.status,
            retry_of_job_id=retry_job.retry_of_job_id,
            retry_of_job_message=None,
            retried_by_job_id=None,
            retried_by_status=None,
            retried_by_finished_at=None,
            retried_by_message=None,
            started_at=retry_job.started_at,
            finished_at=retry_job.finished_at,
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
            message=retry_job.message,
        ),
        return_code=result.return_code,
        command=" ".join(result.command),
    )


def _to_list_item(job) -> CrawlJobListItemResponse:  # type: ignore[no-untyped-def]
    return CrawlJobListItemResponse(
        id=job.id,
        source_site_id=job.source_site_id,
        source_code=job.source_code,
        job_type=job.job_type,
        status=job.status,
        retry_of_job_id=job.retry_of_job_id,
        retry_of_job_message=job.retry_of_job_message,
        retried_by_job_id=job.retried_by_job_id,
        retried_by_status=job.retried_by_status,
        retried_by_finished_at=job.retried_by_finished_at,
        retried_by_message=job.retried_by_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
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
        message=job.message,
    )


def _parse_message_key_values(message: str | None) -> dict[str, str]:
    if not message:
        return {}
    parsed: dict[str, str] = {}
    for part in message.split(";"):
        chunk = part.strip()
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", maxsplit=1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        parsed[normalized_key] = value.strip()
    return parsed


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
