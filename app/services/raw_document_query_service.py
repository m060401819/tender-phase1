from __future__ import annotations

from app.repositories import (
    RawDocumentDetailRecord,
    RawDocumentListResult,
    RawDocumentQueryFilters,
    RawDocumentRepository,
)


class RawDocumentQueryService:
    """Service layer for raw_document list/detail APIs."""

    def __init__(self, repository: RawDocumentRepository) -> None:
        self.repository = repository

    def get_raw_document_detail(self, raw_document_id: int) -> RawDocumentDetailRecord | None:
        return self.repository.get_raw_document_detail(raw_document_id)

    def list_raw_documents(
        self,
        *,
        source_code: str | None,
        document_type: str | None,
        crawl_job_id: int | None,
        content_hash: str | None,
        limit: int,
        offset: int,
    ) -> RawDocumentListResult:
        return self.repository.list_raw_documents(
            filters=RawDocumentQueryFilters(
                source_code=source_code,
                document_type=document_type,
                crawl_job_id=crawl_job_id,
                content_hash=content_hash,
            ),
            limit=limit,
            offset=offset,
        )
