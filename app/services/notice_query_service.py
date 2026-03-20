from __future__ import annotations

from app.repositories import (
    NoticeDetailRecord,
    NoticeListItemRecord,
    NoticeListResult,
    NoticeQueryFilters,
    NoticeRepository,
)


class NoticeQueryService:
    """Service layer for notice list/detail APIs."""

    def __init__(self, repository: NoticeRepository) -> None:
        self.repository = repository

    def list_notices(
        self,
        *,
        keyword: str | None,
        source_code: str | None,
        notice_type: str | None,
        region: str | None,
        limit: int,
        offset: int,
    ) -> NoticeListResult:
        return self.repository.list_notices(
            filters=NoticeQueryFilters(
                keyword=keyword,
                source_code=source_code,
                notice_type=notice_type,
                region=region,
            ),
            limit=limit,
            offset=offset,
        )

    def get_notice_detail(self, notice_id: int) -> NoticeDetailRecord | None:
        return self.repository.get_notice_detail(notice_id)

    def list_notices_for_export(
        self,
        *,
        keyword: str | None,
        source_code: str | None,
        notice_type: str | None,
        region: str | None,
    ) -> list[NoticeListItemRecord]:
        return self.repository.list_notices_for_export(
            filters=NoticeQueryFilters(
                keyword=keyword,
                source_code=source_code,
                notice_type=notice_type,
                region=region,
            )
        )
