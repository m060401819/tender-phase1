from __future__ import annotations

from datetime import date

from app.repositories import (
    NOTICE_SORT_FIELDS,
    NOTICE_SORT_ORDERS,
    NoticeDetailRecord,
    NoticeListItemRecord,
    NoticeListResult,
    NoticeQueryFilters,
    NoticeRelatedRecord,
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
        recent_hours: int | None,
        date_from: date | None,
        date_to: date | None,
        dedup: bool,
        sort_by: str,
        sort_order: str,
        limit: int,
        offset: int,
    ) -> NoticeListResult:
        return self.repository.list_notices(
            filters=NoticeQueryFilters(
                keyword=keyword,
                source_code=source_code,
                notice_type=notice_type,
                region=region,
                recent_hours=recent_hours,
                date_from=date_from,
                date_to=date_to,
            ),
            dedup=dedup,
            sort_by=_normalize_sort_by(sort_by),
            sort_order=_normalize_sort_order(sort_order),
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
        recent_hours: int | None,
        date_from: date | None,
        date_to: date | None,
        dedup: bool,
        sort_by: str,
        sort_order: str,
    ) -> list[NoticeListItemRecord]:
        return self.repository.list_notices_for_export(
            filters=NoticeQueryFilters(
                keyword=keyword,
                source_code=source_code,
                notice_type=notice_type,
                region=region,
                recent_hours=recent_hours,
                date_from=date_from,
                date_to=date_to,
            ),
            dedup=dedup,
            sort_by=_normalize_sort_by(sort_by),
            sort_order=_normalize_sort_order(sort_order),
        )

    def list_related_notices(self, notice_id: int) -> list[NoticeRelatedRecord]:
        return self.repository.list_related_notices(notice_id)


def _normalize_sort_by(sort_by: str) -> str:
    return sort_by if sort_by in NOTICE_SORT_FIELDS else "published_at"


def _normalize_sort_order(sort_order: str) -> str:
    return sort_order if sort_order in NOTICE_SORT_ORDERS else "desc"
