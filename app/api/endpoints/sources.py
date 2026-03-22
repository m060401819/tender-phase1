from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    CrawlJobListItemResponse,
    SourceCrawlJobTriggerRequest,
    SourceCrawlJobTriggerResponse,
    SourceHealthResponse,
    SourceSchedulePatchRequest,
    SourceScheduleResponse,
    SourceSiteCreateRequest,
    SourceSitePatchRequest,
    SourceSiteResponse,
)
from app.db.session import get_db
from app.repositories import SourceSiteRepository
from app.services import (
    CrawlCommandRunner,
    SourceHealthService,
    SourceCrawlTriggerService,
    SourceSiteService,
    SubprocessCrawlCommandRunner,
    get_source_adapter,
    supports_job_type,
    sync_source_schedule,
)

router = APIRouter(tags=["sources"])


def get_source_site_service(db: Session = Depends(get_db)) -> SourceSiteService:
    return SourceSiteService(repository=SourceSiteRepository(db))


def get_crawl_command_runner() -> CrawlCommandRunner:
    return SubprocessCrawlCommandRunner()


def get_source_crawl_trigger_service(
    db: Session = Depends(get_db),
    command_runner: CrawlCommandRunner = Depends(get_crawl_command_runner),
) -> SourceCrawlTriggerService:
    return SourceCrawlTriggerService(session=db, command_runner=command_runner)


def get_source_health_service(db: Session = Depends(get_db)) -> SourceHealthService:
    return SourceHealthService(session=db)


@router.get("/sources", response_model=list[SourceSiteResponse])
def list_sources(service: SourceSiteService = Depends(get_source_site_service)) -> list[SourceSiteResponse]:
    sources = service.list_sources()
    return [
        SourceSiteResponse(
            code=source.code,
            name=source.name,
            base_url=source.base_url,
            official_url=source.official_url,
            list_url=source.list_url,
            description=source.description,
            is_active=source.is_active,
            supports_js_render=source.supports_js_render,
            crawl_interval_minutes=source.crawl_interval_minutes,
            default_max_pages=source.default_max_pages,
        )
        for source in sources
    ]


@router.get("/sources/{code}", response_model=SourceSiteResponse)
def get_source(code: str, service: SourceSiteService = Depends(get_source_site_service)) -> SourceSiteResponse:
    source = service.get_source(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    return SourceSiteResponse(
        code=source.code,
        name=source.name,
        base_url=source.base_url,
        official_url=source.official_url,
        list_url=source.list_url,
        description=source.description,
        is_active=source.is_active,
        supports_js_render=source.supports_js_render,
        crawl_interval_minutes=source.crawl_interval_minutes,
        default_max_pages=source.default_max_pages,
    )


@router.post("/sources", response_model=SourceSiteResponse, status_code=201)
def create_source(
    payload: SourceSiteCreateRequest,
    db: Session = Depends(get_db),
    service: SourceSiteService = Depends(get_source_site_service),
) -> SourceSiteResponse:
    try:
        created = service.create_source(
            source_code=payload.source_code,
            source_name=payload.source_name,
            official_url=str(payload.official_url),
            list_url=str(payload.list_url),
            remark=payload.remark,
            is_active=payload.is_active,
            schedule_enabled=payload.schedule_enabled,
            schedule_days=payload.schedule_days,
            crawl_interval_minutes=payload.crawl_interval_minutes,
            default_max_pages=payload.default_max_pages,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 409 if "source_code already exists" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc

    sync_source_schedule(created.code, fallback_session=db)
    source = service.get_source(created.code)
    if source is None:
        raise HTTPException(status_code=500, detail="created source missing")

    return SourceSiteResponse(
        code=source.code,
        name=source.name,
        base_url=source.base_url,
        official_url=source.official_url,
        list_url=source.list_url,
        description=source.description,
        is_active=source.is_active,
        supports_js_render=source.supports_js_render,
        crawl_interval_minutes=source.crawl_interval_minutes,
        default_max_pages=source.default_max_pages,
    )


@router.patch("/sources/{code}", response_model=SourceSiteResponse)
def patch_source(
    code: str,
    payload: SourceSitePatchRequest,
    db: Session = Depends(get_db),
    service: SourceSiteService = Depends(get_source_site_service),
) -> SourceSiteResponse:
    updates = payload.model_dump(exclude_unset=True)
    if "official_url" in updates:
        updates["official_url"] = str(updates["official_url"])
        updates["base_url"] = updates["official_url"]
    if "list_url" in updates:
        updates["list_url"] = str(updates["list_url"])
    source = service.update_source(code, updates)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if "is_active" in updates:
        sync_source_schedule(source.code, fallback_session=db)
        source = service.get_source(code)
        if source is None:
            raise HTTPException(status_code=404, detail="source not found")

    return SourceSiteResponse(
        code=source.code,
        name=source.name,
        base_url=source.base_url,
        official_url=source.official_url,
        list_url=source.list_url,
        description=source.description,
        is_active=source.is_active,
        supports_js_render=source.supports_js_render,
        crawl_interval_minutes=source.crawl_interval_minutes,
        default_max_pages=source.default_max_pages,
    )


@router.get("/sources/{code}/schedule", response_model=SourceScheduleResponse)
def get_source_schedule(
    code: str,
    service: SourceSiteService = Depends(get_source_site_service),
) -> SourceScheduleResponse:
    source = service.get_source(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    return SourceScheduleResponse(
        source_code=source.code,
        schedule_enabled=source.schedule_enabled,
        schedule_days=source.schedule_days,
        next_scheduled_run_at=source.next_scheduled_run_at,
        last_scheduled_run_at=source.last_scheduled_run_at,
        last_schedule_status=source.last_schedule_status,
    )


@router.get("/sources/{code}/health", response_model=SourceHealthResponse)
def get_source_health(
    code: str,
    health_service: SourceHealthService = Depends(get_source_health_service),
) -> SourceHealthResponse:
    summary = health_service.get_source_health_by_code(code)
    if summary is None:
        raise HTTPException(status_code=404, detail="source not found")

    return SourceHealthResponse(
        source_code=summary.source_code,
        health_status=summary.health_status,
        health_status_label=summary.health_status_label,
        latest_job_id=summary.latest_job_id,
        latest_job_status=summary.latest_job_status,
        latest_job_status_label=summary.latest_job_status_label,
        latest_job_started_at=summary.latest_job_started_at,
        latest_notices_upserted=summary.latest_notices_upserted,
        latest_error_count=summary.latest_error_count,
        recent_7d_job_count=summary.recent_7d_job_count,
        recent_7d_failed_count=summary.recent_7d_failed_count,
        recent_7d_error_count=summary.recent_7d_error_count,
        consecutive_failed=summary.consecutive_failed,
        latest_failure_reason=summary.latest_failure_reason,
    )


@router.patch("/sources/{code}/schedule", response_model=SourceScheduleResponse)
def patch_source_schedule(
    code: str,
    payload: SourceSchedulePatchRequest,
    db: Session = Depends(get_db),
    service: SourceSiteService = Depends(get_source_site_service),
) -> SourceScheduleResponse:
    updates = payload.model_dump(exclude_unset=True)
    source = service.update_source(code, updates)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    sync_source_schedule(source.code, fallback_session=db)
    source = service.get_source(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    return SourceScheduleResponse(
        source_code=source.code,
        schedule_enabled=source.schedule_enabled,
        schedule_days=source.schedule_days,
        next_scheduled_run_at=source.next_scheduled_run_at,
        last_scheduled_run_at=source.last_scheduled_run_at,
        last_schedule_status=source.last_schedule_status,
    )


@router.post("/sources/{code}/crawl-jobs", response_model=SourceCrawlJobTriggerResponse, status_code=201)
def trigger_source_crawl_job(
    code: str,
    payload: SourceCrawlJobTriggerRequest,
    db: Session = Depends(get_db),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
    service: SourceSiteService = Depends(get_source_site_service),
) -> SourceCrawlJobTriggerResponse:
    source_record = service.get_source(code)
    if source_record is None:
        raise HTTPException(status_code=404, detail="source not found")
    source = SourceSiteRepository(db).get_model_by_code(source_record.code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    adapter = get_source_adapter(source.code)
    if adapter is None:
        raise HTTPException(status_code=400, detail="仅保存来源信息，尚未接入抓取逻辑")
    if not supports_job_type(source.code, job_type=payload.job_type):
        supported = " / ".join(adapter.supported_job_types)
        raise HTTPException(
            status_code=400,
            detail=f"source={source.code} 不支持 job_type={payload.job_type}，支持模式: {supported}",
        )

    max_pages = payload.max_pages if payload.max_pages is not None else int(source.default_max_pages)
    if payload.job_type == "backfill":
        if payload.backfill_year is None:
            raise HTTPException(status_code=400, detail="backfill_year is required when job_type=backfill")
        result = trigger_service.trigger_backfill_crawl(
            source=source,
            backfill_year=payload.backfill_year,
            max_pages=max_pages,
            triggered_by=payload.triggered_by,
        )
    else:
        result = trigger_service.trigger_manual_crawl(
            source=source,
            max_pages=max_pages,
            triggered_by=payload.triggered_by,
        )

    job = result.job
    return SourceCrawlJobTriggerResponse(
        source_code=source.code,
        job=CrawlJobListItemResponse(
            id=job.id,
            source_site_id=job.source_site_id,
            source_code=source.code,
            job_type=job.job_type,
            status=job.status,
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
        ),
        return_code=result.return_code,
        command=" ".join(result.command),
    )
