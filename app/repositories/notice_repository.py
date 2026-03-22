from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, String, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models import NoticeVersion, RawDocument, SourceSite, TenderAttachment, TenderNotice

NOTICE_SORT_FIELDS = {"published_at", "deadline_at", "budget_amount", "source_name"}
NOTICE_SORT_ORDERS = {"asc", "desc"}


@dataclass(slots=True)
class NoticeQueryFilters:
    keyword: str | None = None
    source_code: str | None = None
    notice_type: str | None = None
    region: str | None = None
    recent_hours: int | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass(slots=True)
class NoticeListItemRecord:
    id: int
    source_code: str
    source_name: str
    title: str
    notice_type: str
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    current_version_id: int | None
    dedup_key: str
    duplicate_count: int
    is_recent_new: bool


@dataclass(slots=True)
class NoticeListResult:
    items: list[NoticeListItemRecord]
    total: int
    limit: int
    offset: int


@dataclass(slots=True)
class NoticeRelatedRecord:
    id: int
    source_code: str
    source_name: str
    title: str
    published_at: datetime | None
    detail_url: str | None


@dataclass(slots=True)
class NoticeVersionRecord:
    id: int
    notice_id: int
    raw_document_id: int | None
    version_no: int
    is_current: bool
    content_hash: str
    title: str
    notice_type: str
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    budget_currency: str
    change_summary: str | None
    structured_data: dict | None
    raw_document: "RawDocumentSummaryRecord | None"


@dataclass(slots=True)
class RawDocumentSummaryRecord:
    id: int
    document_type: str
    fetched_at: datetime
    storage_uri: str


@dataclass(slots=True)
class TenderAttachmentRecord:
    id: int
    notice_version_id: int | None
    file_name: str
    file_url: str
    attachment_type: str
    mime_type: str | None
    file_size_bytes: int | None
    storage_uri: str | None


@dataclass(slots=True)
class SourceSiteRecord:
    id: int
    code: str
    name: str
    base_url: str
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int


@dataclass(slots=True)
class NoticeDetailRecord:
    id: int
    source_site_id: int
    source_code: str
    external_id: str | None
    project_code: str | None
    title: str
    notice_type: str
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    budget_currency: str
    summary: str | None
    first_published_at: datetime | None
    latest_published_at: datetime | None
    current_version_id: int | None
    source: SourceSiteRecord
    current_version: NoticeVersionRecord | None
    versions: list[NoticeVersionRecord]
    attachments: list[TenderAttachmentRecord]


class NoticeRepository:
    """SQLAlchemy repository for notice list/detail querying."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_notices(
        self,
        *,
        filters: NoticeQueryFilters,
        dedup: bool,
        sort_by: str,
        sort_order: str,
        limit: int = 20,
        offset: int = 0,
    ) -> NoticeListResult:
        base = self._build_list_query(
            filters=filters,
            dedup=dedup,
        )
        base_rows = base.subquery("notice_list")
        order_by = self._build_order_by(base_rows, sort_by=sort_by, sort_order=sort_order)

        total_stmt = select(func.count()).select_from(base_rows)
        total = int(self.session.scalar(total_stmt) or 0)

        rows = self.session.execute(
            select(base_rows)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        ).mappings().all()

        items = [self._to_list_item(row) for row in rows]
        return NoticeListResult(items=items, total=total, limit=limit, offset=offset)

    def list_notices_for_export(
        self,
        *,
        filters: NoticeQueryFilters,
        dedup: bool,
        sort_by: str,
        sort_order: str,
    ) -> list[NoticeListItemRecord]:
        base = self._build_list_query(
            filters=filters,
            dedup=dedup,
        )
        base_rows = base.subquery("notice_list")
        rows = self.session.execute(
            select(base_rows)
            .order_by(*self._build_order_by(base_rows, sort_by=sort_by, sort_order=sort_order))
        ).mappings().all()
        return [self._to_list_item(row) for row in rows]

    def get_notice_detail(self, notice_id: int) -> NoticeDetailRecord | None:
        row = self.session.execute(
            select(TenderNotice, SourceSite)
            .join(SourceSite, SourceSite.id == TenderNotice.source_site_id)
            .where(TenderNotice.id == notice_id)
        ).first()
        if row is None:
            return None

        notice: TenderNotice = row[0]
        source: SourceSite = row[1]

        versions = self._get_versions(notice.id)
        current_version = self._resolve_current_version(notice, versions)
        attachments = self._get_attachments(notice.id)

        return NoticeDetailRecord(
            id=int(notice.id),
            source_site_id=int(notice.source_site_id),
            source_code=source.code,
            external_id=notice.external_id,
            project_code=notice.project_code,
            title=notice.title,
            notice_type=notice.notice_type,
            issuer=notice.issuer,
            region=notice.region,
            published_at=notice.published_at,
            deadline_at=notice.deadline_at,
            budget_amount=notice.budget_amount,
            budget_currency=notice.budget_currency,
            summary=notice.summary,
            first_published_at=notice.first_published_at,
            latest_published_at=notice.latest_published_at,
            current_version_id=int(notice.current_version_id) if notice.current_version_id is not None else None,
            source=SourceSiteRecord(
                id=int(source.id),
                code=source.code,
                name=source.name,
                base_url=source.base_url,
                is_active=bool(source.is_active),
                supports_js_render=bool(source.supports_js_render),
                crawl_interval_minutes=int(source.crawl_interval_minutes),
            ),
            current_version=current_version,
            versions=versions,
            attachments=attachments,
        )

    def list_related_notices(self, notice_id: int) -> list[NoticeRelatedRecord]:
        notice = self.session.scalar(select(TenderNotice).where(TenderNotice.id == notice_id))
        if notice is None:
            return []

        dedup_key = self._dedup_key_for_notice(notice)
        dedup_expr = self._dedup_key_expr()
        rows = self.session.execute(
            select(
                TenderNotice.id.label("id"),
                SourceSite.code.label("source_code"),
                SourceSite.name.label("source_name"),
                TenderNotice.title.label("title"),
                TenderNotice.published_at.label("published_at"),
                RawDocument.url.label("detail_url"),
            )
            .join(SourceSite, SourceSite.id == TenderNotice.source_site_id)
            .outerjoin(NoticeVersion, NoticeVersion.id == TenderNotice.current_version_id)
            .outerjoin(RawDocument, RawDocument.id == NoticeVersion.raw_document_id)
            .where(dedup_expr == dedup_key)
            .order_by(
                TenderNotice.published_at.is_(None),
                TenderNotice.published_at.desc(),
                TenderNotice.id.desc(),
            )
        ).mappings().all()

        return [
            NoticeRelatedRecord(
                id=int(row["id"]),
                source_code=str(row["source_code"]),
                source_name=str(row["source_name"]),
                title=str(row["title"]),
                published_at=row["published_at"],
                detail_url=row["detail_url"],
            )
            for row in rows
        ]

    def _build_list_query(
        self,
        *,
        filters: NoticeQueryFilters,
        dedup: bool,
    ) -> Select:
        base_rows = self._build_base_rows_query(filters=filters).subquery("notice_rows")
        if dedup:
            ranked_rows = self._build_ranked_rows_query(base_rows).subquery("notice_ranked")
            return (
                select(
                    ranked_rows.c.id,
                    ranked_rows.c.source_code,
                    ranked_rows.c.source_name,
                    ranked_rows.c.title,
                    ranked_rows.c.notice_type,
                    ranked_rows.c.issuer,
                    ranked_rows.c.region,
                    ranked_rows.c.published_at,
                    ranked_rows.c.deadline_at,
                    ranked_rows.c.budget_amount,
                    ranked_rows.c.current_version_id,
                    ranked_rows.c.dedup_key,
                    ranked_rows.c.duplicate_count,
                    ranked_rows.c.is_recent_new,
                )
                .where(ranked_rows.c.row_rank == 1)
            )

        return select(
            base_rows.c.id,
            base_rows.c.source_code,
            base_rows.c.source_name,
            base_rows.c.title,
            base_rows.c.notice_type,
            base_rows.c.issuer,
            base_rows.c.region,
            base_rows.c.published_at,
            base_rows.c.deadline_at,
            base_rows.c.budget_amount,
            base_rows.c.current_version_id,
            base_rows.c.dedup_key,
            literal(1).label("duplicate_count"),
            base_rows.c.is_recent_new,
        )

    def _build_base_rows_query(self, *, filters: NoticeQueryFilters) -> Select:
        dedup_key_expr = self._dedup_key_expr()
        stmt = select(
            TenderNotice.id.label("id"),
            SourceSite.code.label("source_code"),
            SourceSite.name.label("source_name"),
            TenderNotice.title.label("title"),
            TenderNotice.notice_type.label("notice_type"),
            TenderNotice.issuer.label("issuer"),
            TenderNotice.region.label("region"),
            TenderNotice.published_at.label("published_at"),
            TenderNotice.deadline_at.label("deadline_at"),
            TenderNotice.budget_amount.label("budget_amount"),
            TenderNotice.current_version_id.label("current_version_id"),
            dedup_key_expr.label("dedup_key"),
            self._is_recent_new_expr().label("is_recent_new"),
        ).join(SourceSite, SourceSite.id == TenderNotice.source_site_id)

        normalized_keyword = (filters.keyword or "").strip()
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            stmt = stmt.where(
                or_(
                    TenderNotice.title.ilike(pattern),
                    TenderNotice.issuer.ilike(pattern),
                    TenderNotice.region.ilike(pattern),
                )
            )

        if filters.source_code:
            stmt = stmt.where(SourceSite.code == filters.source_code)
        if filters.notice_type:
            stmt = stmt.where(TenderNotice.notice_type == filters.notice_type)
        if filters.region:
            stmt = stmt.where(TenderNotice.region == filters.region)
        if filters.recent_hours is not None:
            start_at = datetime.now(timezone.utc) - timedelta(hours=filters.recent_hours)
            recent_version_exists = (
                select(NoticeVersion.id)
                .where(
                    NoticeVersion.notice_id == TenderNotice.id,
                    NoticeVersion.created_at >= start_at,
                )
                .exists()
            )
            stmt = stmt.where(
                or_(
                    TenderNotice.created_at >= start_at,
                    recent_version_exists,
                )
            )
        if filters.date_from is not None:
            stmt = stmt.where(TenderNotice.published_at >= _to_start_of_day(filters.date_from))
        if filters.date_to is not None:
            stmt = stmt.where(TenderNotice.published_at <= _to_end_of_day(filters.date_to))

        return stmt

    def _build_ranked_rows_query(self, base_rows: Any) -> Select:
        rank_order = (
            base_rows.c.is_recent_new.desc(),
            base_rows.c.published_at.is_(None),
            base_rows.c.published_at.desc(),
            base_rows.c.id.desc(),
        )
        return select(
            base_rows.c.id,
            base_rows.c.source_code,
            base_rows.c.source_name,
            base_rows.c.title,
            base_rows.c.notice_type,
            base_rows.c.issuer,
            base_rows.c.region,
            base_rows.c.published_at,
            base_rows.c.deadline_at,
            base_rows.c.budget_amount,
            base_rows.c.current_version_id,
            base_rows.c.dedup_key,
            base_rows.c.is_recent_new,
            func.row_number().over(partition_by=base_rows.c.dedup_key, order_by=rank_order).label("row_rank"),
            func.count().over(partition_by=base_rows.c.dedup_key).label("duplicate_count"),
        )

    def _build_order_by(self, table: Any, *, sort_by: str, sort_order: str) -> tuple[Any, ...]:
        normalized_sort_by = sort_by if sort_by in NOTICE_SORT_FIELDS else "published_at"
        normalized_sort_order = sort_order if sort_order in NOTICE_SORT_ORDERS else "desc"

        if normalized_sort_by == "deadline_at":
            column = table.c.deadline_at
        elif normalized_sort_by == "budget_amount":
            column = table.c.budget_amount
        elif normalized_sort_by == "source_name":
            column = table.c.source_name
        else:
            column = table.c.published_at

        if normalized_sort_order == "asc":
            return (
                column.is_(None),
                column.asc(),
                table.c.id.desc(),
            )
        if normalized_sort_by == "published_at":
            return (
                table.c.is_recent_new.desc(),
                column.is_(None),
                column.desc(),
                table.c.id.desc(),
            )
        return (
            column.is_(None),
            column.desc(),
            table.c.id.desc(),
        )

    def _get_versions(self, notice_id: int) -> list[NoticeVersionRecord]:
        version_rows = self.session.scalars(
            select(NoticeVersion)
            .where(NoticeVersion.notice_id == notice_id)
            .order_by(NoticeVersion.version_no.desc(), NoticeVersion.id.desc())
        ).all()
        if not version_rows:
            return []

        raw_document_ids = {
            int(item.raw_document_id)
            for item in version_rows
            if item.raw_document_id is not None
        }
        raw_document_map = self._get_raw_document_map(raw_document_ids)
        return [self._to_version(item, raw_document_map.get(int(item.raw_document_id or 0))) for item in version_rows]

    def _resolve_current_version(
        self,
        notice: TenderNotice,
        versions: list[NoticeVersionRecord],
    ) -> NoticeVersionRecord | None:
        if not versions:
            return None

        if notice.current_version_id is not None:
            for item in versions:
                if item.id == int(notice.current_version_id):
                    return item

        for item in versions:
            if item.is_current:
                return item

        return versions[0]

    def _get_raw_document_map(self, ids: set[int]) -> dict[int, RawDocumentSummaryRecord]:
        if not ids:
            return {}
        rows = self.session.scalars(
            select(RawDocument).where(RawDocument.id.in_(ids))
        ).all()
        return {
            int(item.id): RawDocumentSummaryRecord(
                id=int(item.id),
                document_type=item.document_type,
                fetched_at=item.fetched_at,
                storage_uri=item.storage_uri,
            )
            for item in rows
        }

    def _get_attachments(self, notice_id: int) -> list[TenderAttachmentRecord]:
        rows = self.session.scalars(
            select(TenderAttachment)
            .where(
                TenderAttachment.notice_id == notice_id,
                TenderAttachment.is_deleted.is_(False),
            )
            .order_by(TenderAttachment.id.asc())
        ).all()
        return [
            TenderAttachmentRecord(
                id=int(item.id),
                notice_version_id=int(item.notice_version_id) if item.notice_version_id is not None else None,
                file_name=item.file_name,
                file_url=item.file_url,
                attachment_type=item.attachment_type,
                mime_type=item.mime_type,
                file_size_bytes=int(item.file_size_bytes) if item.file_size_bytes is not None else None,
                storage_uri=item.storage_uri,
            )
            for item in rows
        ]

    def _to_list_item(self, row: Any) -> NoticeListItemRecord:
        return NoticeListItemRecord(
            id=int(row["id"]),
            source_code=str(row["source_code"]),
            source_name=str(row["source_name"]),
            title=str(row["title"]),
            notice_type=str(row["notice_type"]),
            issuer=row["issuer"],
            region=row["region"],
            published_at=row["published_at"],
            deadline_at=row["deadline_at"],
            budget_amount=row["budget_amount"],
            current_version_id=int(row["current_version_id"]) if row["current_version_id"] is not None else None,
            dedup_key=str(row["dedup_key"]),
            duplicate_count=int(row["duplicate_count"] or 1),
            is_recent_new=bool(row["is_recent_new"]),
        )

    def _to_version(
        self,
        version: NoticeVersion,
        raw_document: RawDocumentSummaryRecord | None,
    ) -> NoticeVersionRecord:
        return NoticeVersionRecord(
            id=int(version.id),
            notice_id=int(version.notice_id),
            raw_document_id=int(version.raw_document_id) if version.raw_document_id is not None else None,
            version_no=int(version.version_no),
            is_current=bool(version.is_current),
            content_hash=version.content_hash,
            title=version.title,
            notice_type=version.notice_type,
            issuer=version.issuer,
            region=version.region,
            published_at=version.published_at,
            deadline_at=version.deadline_at,
            budget_amount=version.budget_amount,
            budget_currency=version.budget_currency,
            change_summary=version.change_summary,
            structured_data=version.structured_data,
            raw_document=raw_document,
        )

    def _dedup_key_expr(self):  # type: ignore[no-untyped-def]
        normalized_dedup_key = func.nullif(func.trim(TenderNotice.dedup_key), "")
        normalized_source_duplicate_key = func.nullif(func.trim(TenderNotice.source_duplicate_key), "")
        normalized_hash = func.nullif(func.trim(TenderNotice.dedup_hash), "")
        fallback = (
            literal("fallback:")
            + cast(TenderNotice.source_site_id, String())
            + literal("|")
            + func.coalesce(func.trim(TenderNotice.external_id), "")
            + literal("|")
            + func.coalesce(func.trim(TenderNotice.project_code), "")
            + literal("|")
            + func.coalesce(func.trim(TenderNotice.title), "")
        )
        return func.coalesce(normalized_dedup_key, normalized_source_duplicate_key, normalized_hash, fallback)

    def _dedup_key_for_notice(self, notice: TenderNotice) -> str:
        dedup_key = (notice.dedup_key or "").strip()
        if dedup_key:
            return dedup_key
        source_duplicate_key = (notice.source_duplicate_key or "").strip()
        if source_duplicate_key:
            return source_duplicate_key
        dedup_hash = (notice.dedup_hash or "").strip()
        if dedup_hash:
            return dedup_hash
        return (
            f"fallback:{int(notice.source_site_id)}|"
            f"{(notice.external_id or '').strip()}|"
            f"{(notice.project_code or '').strip()}|"
            f"{(notice.title or '').strip()}"
        )

    def _is_recent_new_expr(self):  # type: ignore[no-untyped-def]
        recent_start_at = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_version_exists = (
            select(NoticeVersion.id)
            .where(
                NoticeVersion.notice_id == TenderNotice.id,
                NoticeVersion.created_at >= recent_start_at,
            )
            .exists()
        )
        return or_(
            TenderNotice.created_at >= recent_start_at,
            recent_version_exists,
        )


def _to_start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _to_end_of_day(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=timezone.utc)
