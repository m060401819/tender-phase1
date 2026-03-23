from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    CrawlErrorDetailResponse,
    CrawlErrorListItemResponse,
    CrawlErrorListResponse,
    CrawlErrorNoticeSummaryResponse,
    CrawlErrorNoticeVersionSummaryResponse,
    CrawlErrorRawDocumentSummaryResponse,
    CrawlErrorStage,
    NoticeType,
)
from app.db.session import get_db
from app.repositories import CrawlErrorRepository
from app.services import CrawlErrorQueryService

router = APIRouter(tags=["crawl-errors"])


@router.get("/crawl-errors", response_model=CrawlErrorListResponse)
def list_crawl_errors(
    source_code: str | None = Query(default=None),
    stage: CrawlErrorStage | None = Query(default=None),
    crawl_job_id: int | None = Query(default=None, ge=1),
    error_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CrawlErrorListResponse:
    service = CrawlErrorQueryService(repository=CrawlErrorRepository(db))
    result = service.list_crawl_errors(
        source_code=source_code,
        stage=stage.value if stage else None,
        crawl_job_id=crawl_job_id,
        error_type=error_type,
        limit=limit,
        offset=offset,
    )
    return CrawlErrorListResponse(
        items=[
            CrawlErrorListItemResponse(
                id=item.id,
                source_code=item.source_code,
                crawl_job_id=item.crawl_job_id,
                stage=_to_crawl_error_stage(item.stage),
                error_type=item.error_type,
                message=item.message,
                url=item.url,
                created_at=item.created_at,
            )
            for item in result.items
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/crawl-errors/{error_id}", response_model=CrawlErrorDetailResponse)
def get_crawl_error_detail(error_id: int, db: Session = Depends(get_db)) -> CrawlErrorDetailResponse:
    service = CrawlErrorQueryService(repository=CrawlErrorRepository(db))
    item = service.get_crawl_error_detail(error_id)
    if item is None:
        raise HTTPException(status_code=404, detail="crawl_error not found")

    return CrawlErrorDetailResponse(
        id=item.id,
        source_code=item.source_code,
        crawl_job_id=item.crawl_job_id,
        stage=_to_crawl_error_stage(item.stage),
        error_type=item.error_type,
        message=item.message,
        detail=item.detail,
        url=item.url,
        traceback=item.traceback,
        created_at=item.created_at,
        raw_document=(
            CrawlErrorRawDocumentSummaryResponse(
                id=item.raw_document.id,
                document_type=item.raw_document.document_type,
                fetched_at=item.raw_document.fetched_at,
                storage_uri=item.raw_document.storage_uri,
            )
            if item.raw_document is not None
            else None
        ),
        notice=(
            CrawlErrorNoticeSummaryResponse(
                id=item.notice.id,
                source_code=item.notice.source_code,
                title=item.notice.title,
                notice_type=_to_notice_type(item.notice.notice_type),
                current_version_id=item.notice.current_version_id,
            )
            if item.notice is not None
            else None
        ),
        notice_version=(
            CrawlErrorNoticeVersionSummaryResponse(
                id=item.notice_version.id,
                notice_id=item.notice_version.notice_id,
                version_no=item.notice_version.version_no,
                is_current=item.notice_version.is_current,
                title=item.notice_version.title,
                notice_type=_to_notice_type(item.notice_version.notice_type),
            )
            if item.notice_version is not None
            else None
        ),
    )


def _to_crawl_error_stage(value: str) -> CrawlErrorStage:
    return CrawlErrorStage(value)


def _to_notice_type(value: str) -> NoticeType:
    return NoticeType(value)
