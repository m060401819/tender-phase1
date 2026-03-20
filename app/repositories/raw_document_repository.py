from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import NoticeVersion, RawDocument, SourceSite, TenderNotice


@dataclass(slots=True)
class RawDocumentQueryFilters:
    source_code: str | None = None
    document_type: str | None = None
    crawl_job_id: int | None = None
    content_hash: str | None = None


@dataclass(slots=True)
class RawDocumentListItemRecord:
    id: int
    source_code: str
    crawl_job_id: int | None
    url: str
    normalized_url: str
    document_type: str
    fetched_at: datetime
    storage_uri: str
    mime_type: str | None
    title: str | None
    content_hash: str | None


@dataclass(slots=True)
class RawDocumentListResult:
    items: list[RawDocumentListItemRecord]
    total: int
    limit: int
    offset: int


@dataclass(slots=True)
class RawDocumentNoticeVersionSummaryRecord:
    id: int
    notice_id: int
    version_no: int
    is_current: bool
    title: str
    notice_type: str


@dataclass(slots=True)
class RawDocumentNoticeSummaryRecord:
    id: int
    source_code: str
    title: str
    notice_type: str
    published_at: datetime | None
    current_version_id: int | None


@dataclass(slots=True)
class RawDocumentDetailRecord:
    id: int
    source_code: str
    crawl_job_id: int | None
    url: str
    normalized_url: str
    document_type: str
    fetched_at: datetime
    storage_uri: str
    mime_type: str | None
    title: str | None
    content_hash: str | None
    notice_version: RawDocumentNoticeVersionSummaryRecord | None
    tender_notice: RawDocumentNoticeSummaryRecord | None


class RawDocumentRepository:
    """SQLAlchemy repository for raw_document list/detail querying."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_raw_documents(
        self,
        *,
        filters: RawDocumentQueryFilters,
        limit: int = 20,
        offset: int = 0,
    ) -> RawDocumentListResult:
        base = self._build_list_query(filters)
        total_stmt = select(func.count()).select_from(base.subquery())
        total = int(self.session.scalar(total_stmt) or 0)

        rows = self.session.execute(
            base.order_by(
                RawDocument.fetched_at.is_(None),
                RawDocument.fetched_at.desc(),
                RawDocument.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()

        items = [self._to_list_item(raw_document=row[0], source_code=row[1]) for row in rows]
        return RawDocumentListResult(items=items, total=total, limit=limit, offset=offset)

    def get_raw_document_detail(self, raw_document_id: int) -> RawDocumentDetailRecord | None:
        row = self.session.execute(
            select(RawDocument, SourceSite.code)
            .join(SourceSite, SourceSite.id == RawDocument.source_site_id)
            .where(RawDocument.id == raw_document_id)
        ).first()
        if row is None:
            return None

        raw_document: RawDocument = row[0]
        source_code: str = row[1]

        relation = self.session.execute(
            select(NoticeVersion, TenderNotice, SourceSite.code)
            .join(TenderNotice, TenderNotice.id == NoticeVersion.notice_id)
            .join(SourceSite, SourceSite.id == TenderNotice.source_site_id)
            .where(NoticeVersion.raw_document_id == raw_document.id)
            .order_by(
                NoticeVersion.is_current.desc(),
                NoticeVersion.version_no.desc(),
                NoticeVersion.id.desc(),
            )
        ).first()

        notice_version = None
        tender_notice = None
        if relation is not None:
            version: NoticeVersion = relation[0]
            notice: TenderNotice = relation[1]
            notice_source_code: str = relation[2]

            notice_version = RawDocumentNoticeVersionSummaryRecord(
                id=int(version.id),
                notice_id=int(version.notice_id),
                version_no=int(version.version_no),
                is_current=bool(version.is_current),
                title=version.title,
                notice_type=version.notice_type,
            )
            tender_notice = RawDocumentNoticeSummaryRecord(
                id=int(notice.id),
                source_code=notice_source_code,
                title=notice.title,
                notice_type=notice.notice_type,
                published_at=notice.published_at,
                current_version_id=int(notice.current_version_id) if notice.current_version_id is not None else None,
            )

        return RawDocumentDetailRecord(
            id=int(raw_document.id),
            source_code=source_code,
            crawl_job_id=int(raw_document.crawl_job_id) if raw_document.crawl_job_id is not None else None,
            url=raw_document.url,
            normalized_url=raw_document.normalized_url,
            document_type=raw_document.document_type,
            fetched_at=raw_document.fetched_at,
            storage_uri=raw_document.storage_uri,
            mime_type=raw_document.mime_type,
            title=raw_document.title,
            content_hash=raw_document.content_hash,
            notice_version=notice_version,
            tender_notice=tender_notice,
        )

    def _build_list_query(self, filters: RawDocumentQueryFilters) -> Select:
        stmt = select(RawDocument, SourceSite.code).join(SourceSite, SourceSite.id == RawDocument.source_site_id)

        if filters.source_code:
            stmt = stmt.where(SourceSite.code == filters.source_code)
        if filters.document_type:
            stmt = stmt.where(RawDocument.document_type == filters.document_type)
        if filters.crawl_job_id is not None:
            stmt = stmt.where(RawDocument.crawl_job_id == filters.crawl_job_id)
        if filters.content_hash:
            stmt = stmt.where(RawDocument.content_hash == filters.content_hash)

        return stmt

    def _to_list_item(self, *, raw_document: RawDocument, source_code: str) -> RawDocumentListItemRecord:
        return RawDocumentListItemRecord(
            id=int(raw_document.id),
            source_code=source_code,
            crawl_job_id=int(raw_document.crawl_job_id) if raw_document.crawl_job_id is not None else None,
            url=raw_document.url,
            normalized_url=raw_document.normalized_url,
            document_type=raw_document.document_type,
            fetched_at=raw_document.fetched_at,
            storage_uri=raw_document.storage_uri,
            mime_type=raw_document.mime_type,
            title=raw_document.title,
            content_hash=raw_document.content_hash,
        )
