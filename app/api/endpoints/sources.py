from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    CrawlJobListItemResponse,
    SourceCrawlJobTriggerRequest,
    SourceCrawlJobTriggerResponse,
    SourceSitePatchRequest,
    SourceSiteResponse,
)
from app.db.session import get_db
from app.repositories import SourceSiteRepository
from app.services import (
    CrawlCommandRunner,
    SourceCrawlTriggerService,
    SourceSiteService,
    SubprocessCrawlCommandRunner,
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


@router.get("/sources", response_model=list[SourceSiteResponse])
def list_sources(service: SourceSiteService = Depends(get_source_site_service)) -> list[SourceSiteResponse]:
    sources = service.list_sources()
    return [
        SourceSiteResponse(
            code=source.code,
            name=source.name,
            base_url=source.base_url,
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
    service: SourceSiteService = Depends(get_source_site_service),
) -> SourceSiteResponse:
    updates = payload.model_dump(exclude_unset=True)
    source = service.update_source(code, updates)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    return SourceSiteResponse(
        code=source.code,
        name=source.name,
        base_url=source.base_url,
        description=source.description,
        is_active=source.is_active,
        supports_js_render=source.supports_js_render,
        crawl_interval_minutes=source.crawl_interval_minutes,
        default_max_pages=source.default_max_pages,
    )


@router.post("/sources/{code}/crawl-jobs", response_model=SourceCrawlJobTriggerResponse, status_code=201)
def trigger_source_crawl_job(
    code: str,
    payload: SourceCrawlJobTriggerRequest,
    db: Session = Depends(get_db),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
) -> SourceCrawlJobTriggerResponse:
    source = SourceSiteRepository(db).get_model_by_code(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    result = trigger_service.trigger_manual_crawl(
        source=source,
        max_pages=payload.max_pages,
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
            message=job.message,
        ),
        return_code=result.return_code,
        command=" ".join(result.command),
    )
