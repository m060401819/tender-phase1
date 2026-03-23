from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    RawDocumentDetailResponse,
    RawDocumentListItemResponse,
    RawDocumentListResponse,
    RawDocumentNoticeSummaryResponse,
    RawDocumentNoticeVersionSummaryResponse,
    NoticeType,
)
from app.db.session import get_db
from app.repositories import RawDocumentRepository
from app.services import RawDocumentQueryService

router = APIRouter(tags=["raw-documents"])


@router.get("/raw-documents", response_model=RawDocumentListResponse)
def list_raw_documents(
    source_code: str | None = Query(default=None),
    document_type: str | None = Query(default=None),
    crawl_job_id: int | None = Query(default=None, ge=1),
    content_hash: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> RawDocumentListResponse:
    service = RawDocumentQueryService(repository=RawDocumentRepository(db))
    result = service.list_raw_documents(
        source_code=source_code,
        document_type=document_type,
        crawl_job_id=crawl_job_id,
        content_hash=content_hash,
        limit=limit,
        offset=offset,
    )

    return RawDocumentListResponse(
        items=[
            RawDocumentListItemResponse(
                id=item.id,
                source_code=item.source_code,
                crawl_job_id=item.crawl_job_id,
                url=item.url,
                normalized_url=item.normalized_url,
                document_type=item.document_type,
                fetched_at=item.fetched_at,
                storage_uri=item.storage_uri,
                mime_type=item.mime_type,
                title=item.title,
                content_hash=item.content_hash,
            )
            for item in result.items
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/raw-documents/{raw_document_id}", response_model=RawDocumentDetailResponse)
def get_raw_document_detail(raw_document_id: int, db: Session = Depends(get_db)) -> RawDocumentDetailResponse:
    service = RawDocumentQueryService(repository=RawDocumentRepository(db))
    item = service.get_raw_document_detail(raw_document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="raw_document not found")

    return RawDocumentDetailResponse(
        id=item.id,
        source_code=item.source_code,
        crawl_job_id=item.crawl_job_id,
        url=item.url,
        normalized_url=item.normalized_url,
        document_type=item.document_type,
        fetched_at=item.fetched_at,
        storage_uri=item.storage_uri,
        mime_type=item.mime_type,
        title=item.title,
        content_hash=item.content_hash,
        notice_version=(
            RawDocumentNoticeVersionSummaryResponse(
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
        tender_notice=(
            RawDocumentNoticeSummaryResponse(
                id=item.tender_notice.id,
                source_code=item.tender_notice.source_code,
                title=item.tender_notice.title,
                notice_type=_to_notice_type(item.tender_notice.notice_type),
                published_at=item.tender_notice.published_at,
                current_version_id=item.tender_notice.current_version_id,
            )
            if item.tender_notice is not None
            else None
        ),
    )


def _to_notice_type(value: str) -> NoticeType:
    return NoticeType(value)
