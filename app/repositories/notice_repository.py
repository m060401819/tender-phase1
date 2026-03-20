from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import NoticeVersion, RawDocument, SourceSite, TenderAttachment, TenderNotice


@dataclass(slots=True)
class NoticeQueryFilters:
    keyword: str | None = None
    source_code: str | None = None
    notice_type: str | None = None
    region: str | None = None


@dataclass(slots=True)
class NoticeListItemRecord:
    id: int
    source_code: str
    title: str
    notice_type: str
    issuer: str | None
    region: str | None
    published_at: datetime | None
    deadline_at: datetime | None
    budget_amount: Decimal | None
    current_version_id: int | None


@dataclass(slots=True)
class NoticeListResult:
    items: list[NoticeListItemRecord]
    total: int
    limit: int
    offset: int


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
        limit: int = 20,
        offset: int = 0,
    ) -> NoticeListResult:
        base = self._build_list_query(filters)
        order_by = self._list_order_by()

        total_stmt = select(func.count()).select_from(base.subquery())
        total = int(self.session.scalar(total_stmt) or 0)

        rows = self.session.execute(
            base.order_by(*order_by)
            .limit(limit)
            .offset(offset)
        ).all()

        items = [self._to_list_item(notice=row[0], source_code=row[1]) for row in rows]
        return NoticeListResult(items=items, total=total, limit=limit, offset=offset)

    def list_notices_for_export(self, *, filters: NoticeQueryFilters) -> list[NoticeListItemRecord]:
        base = self._build_list_query(filters)
        rows = self.session.execute(base.order_by(*self._list_order_by())).all()
        return [self._to_list_item(notice=row[0], source_code=row[1]) for row in rows]

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

    def _build_list_query(self, filters: NoticeQueryFilters) -> Select:
        stmt = select(TenderNotice, SourceSite.code).join(SourceSite, SourceSite.id == TenderNotice.source_site_id)

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

        return stmt

    def _list_order_by(self) -> tuple:
        return (
            TenderNotice.published_at.is_(None),
            TenderNotice.published_at.desc(),
            TenderNotice.id.desc(),
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

    def _to_list_item(self, *, notice: TenderNotice, source_code: str) -> NoticeListItemRecord:
        return NoticeListItemRecord(
            id=int(notice.id),
            source_code=source_code,
            title=notice.title,
            notice_type=notice.notice_type,
            issuer=notice.issuer,
            region=notice.region,
            published_at=notice.published_at,
            deadline_at=notice.deadline_at,
            budget_amount=notice.budget_amount,
            current_version_id=int(notice.current_version_id) if notice.current_version_id is not None else None,
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
