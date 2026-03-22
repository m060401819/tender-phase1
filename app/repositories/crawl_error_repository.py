from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import CrawlError, NoticeVersion, RawDocument, SourceSite, TenderNotice


@dataclass(slots=True)
class CrawlErrorQueryFilters:
    source_code: str | None = None
    stage: str | None = None
    crawl_job_id: int | None = None
    error_type: str | None = None


@dataclass(slots=True)
class CrawlErrorListItemRecord:
    id: int
    source_code: str
    crawl_job_id: int | None
    stage: str
    error_type: str
    message: str
    url: str | None
    created_at: datetime


@dataclass(slots=True)
class CrawlErrorListResult:
    items: list[CrawlErrorListItemRecord]
    total: int
    limit: int
    offset: int


@dataclass(slots=True)
class CrawlErrorSourceSummaryRecord:
    source_code: str
    recent_error_count: int
    latest_error_id: int
    latest_error_message: str
    latest_error_created_at: datetime


@dataclass(slots=True)
class CrawlErrorRawDocumentSummaryRecord:
    id: int
    document_type: str
    fetched_at: datetime
    storage_uri: str


@dataclass(slots=True)
class CrawlErrorNoticeSummaryRecord:
    id: int
    source_code: str
    title: str
    notice_type: str
    current_version_id: int | None


@dataclass(slots=True)
class CrawlErrorNoticeVersionSummaryRecord:
    id: int
    notice_id: int
    version_no: int
    is_current: bool
    title: str
    notice_type: str


@dataclass(slots=True)
class CrawlErrorDetailRecord:
    id: int
    source_code: str
    crawl_job_id: int | None
    raw_document_id: int | None
    stage: str
    error_type: str
    message: str
    detail: str | None
    url: str | None
    traceback: str | None
    created_at: datetime
    raw_document: CrawlErrorRawDocumentSummaryRecord | None
    notice: CrawlErrorNoticeSummaryRecord | None
    notice_version: CrawlErrorNoticeVersionSummaryRecord | None


class CrawlErrorRepository:
    """SQLAlchemy repository for crawl_error list/detail querying."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_errors(
        self,
        *,
        filters: CrawlErrorQueryFilters,
        limit: int = 20,
        offset: int = 0,
    ) -> CrawlErrorListResult:
        base = self._build_list_query(filters)
        total_stmt = select(func.count()).select_from(base.subquery())
        total = int(self.session.scalar(total_stmt) or 0)

        rows = self.session.execute(
            base.order_by(CrawlError.created_at.desc(), CrawlError.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        items = [self._to_list_item(error=row[0], source_code=row[1]) for row in rows]
        return CrawlErrorListResult(items=items, total=total, limit=limit, offset=offset)

    def get_error_detail(self, error_id: int) -> CrawlErrorDetailRecord | None:
        row = self.session.execute(
            select(CrawlError, SourceSite.code)
            .join(SourceSite, SourceSite.id == CrawlError.source_site_id)
            .where(CrawlError.id == error_id)
        ).first()
        if row is None:
            return None

        error: CrawlError = row[0]
        source_code: str = row[1]

        raw_document = self._get_raw_document_summary(error.raw_document_id)
        notice, notice_version = self._get_notice_relation_by_raw_document(error.raw_document_id)

        return CrawlErrorDetailRecord(
            id=int(error.id),
            source_code=source_code,
            crawl_job_id=int(error.crawl_job_id) if error.crawl_job_id is not None else None,
            raw_document_id=int(error.raw_document_id) if error.raw_document_id is not None else None,
            stage=error.stage,
            error_type=error.error_type,
            message=error.error_message,
            detail=error.error_message,
            url=error.url,
            traceback=error.traceback,
            created_at=error.created_at,
            raw_document=raw_document,
            notice=notice,
            notice_version=notice_version,
        )

    def list_recent_source_summaries(
        self,
        *,
        filters: CrawlErrorQueryFilters,
        recent_days: int = 7,
        limit: int = 20,
    ) -> list[CrawlErrorSourceSummaryRecord]:
        since = datetime.now(timezone.utc) - timedelta(days=recent_days)
        summary_stmt = (
            select(
                CrawlError.source_site_id.label("source_site_id"),
                SourceSite.code.label("source_code"),
                func.count(CrawlError.id).label("recent_error_count"),
                func.max(CrawlError.id).label("latest_error_id"),
            )
            .join(SourceSite, SourceSite.id == CrawlError.source_site_id)
            .where(CrawlError.created_at >= since)
        )
        if filters.source_code:
            summary_stmt = summary_stmt.where(SourceSite.code == filters.source_code)
        if filters.stage:
            summary_stmt = summary_stmt.where(CrawlError.stage == filters.stage)
        if filters.crawl_job_id is not None:
            summary_stmt = summary_stmt.where(CrawlError.crawl_job_id == filters.crawl_job_id)
        if filters.error_type:
            summary_stmt = summary_stmt.where(CrawlError.error_type == filters.error_type)

        summary_rows = self.session.execute(
            summary_stmt
            .group_by(CrawlError.source_site_id, SourceSite.code)
            .order_by(func.count(CrawlError.id).desc(), func.max(CrawlError.id).desc())
            .limit(limit)
        ).all()
        if not summary_rows:
            return []

        latest_error_ids = [int(row.latest_error_id) for row in summary_rows if row.latest_error_id is not None]
        latest_error_rows = self.session.execute(
            select(CrawlError.id, CrawlError.error_message, CrawlError.created_at).where(CrawlError.id.in_(latest_error_ids))
        ).all()
        latest_error_map = {
            int(error_id): {
                "message": message,
                "created_at": created_at,
            }
            for error_id, message, created_at in latest_error_rows
        }

        items: list[CrawlErrorSourceSummaryRecord] = []
        for row in summary_rows:
            latest_error_id = int(row.latest_error_id or 0)
            latest_payload = latest_error_map.get(latest_error_id)
            if latest_payload is None:
                continue
            items.append(
                CrawlErrorSourceSummaryRecord(
                    source_code=row.source_code,
                    recent_error_count=int(row.recent_error_count or 0),
                    latest_error_id=latest_error_id,
                    latest_error_message=str(latest_payload["message"] or ""),
                    latest_error_created_at=latest_payload["created_at"],
                )
            )
        return items

    def _build_list_query(self, filters: CrawlErrorQueryFilters) -> Select:
        stmt = select(CrawlError, SourceSite.code).join(SourceSite, SourceSite.id == CrawlError.source_site_id)
        if filters.source_code:
            stmt = stmt.where(SourceSite.code == filters.source_code)
        if filters.stage:
            stmt = stmt.where(CrawlError.stage == filters.stage)
        if filters.crawl_job_id is not None:
            stmt = stmt.where(CrawlError.crawl_job_id == filters.crawl_job_id)
        if filters.error_type:
            stmt = stmt.where(CrawlError.error_type == filters.error_type)
        return stmt

    def _to_list_item(self, *, error: CrawlError, source_code: str) -> CrawlErrorListItemRecord:
        return CrawlErrorListItemRecord(
            id=int(error.id),
            source_code=source_code,
            crawl_job_id=int(error.crawl_job_id) if error.crawl_job_id is not None else None,
            stage=error.stage,
            error_type=error.error_type,
            message=error.error_message,
            url=error.url,
            created_at=error.created_at,
        )

    def _get_raw_document_summary(self, raw_document_id: int | None) -> CrawlErrorRawDocumentSummaryRecord | None:
        if raw_document_id is None:
            return None
        row = self.session.scalar(select(RawDocument).where(RawDocument.id == raw_document_id))
        if row is None:
            return None
        return CrawlErrorRawDocumentSummaryRecord(
            id=int(row.id),
            document_type=row.document_type,
            fetched_at=row.fetched_at,
            storage_uri=row.storage_uri,
        )

    def _get_notice_relation_by_raw_document(
        self,
        raw_document_id: int | None,
    ) -> tuple[CrawlErrorNoticeSummaryRecord | None, CrawlErrorNoticeVersionSummaryRecord | None]:
        if raw_document_id is None:
            return None, None

        row = self.session.execute(
            select(NoticeVersion, TenderNotice, SourceSite.code)
            .join(TenderNotice, TenderNotice.id == NoticeVersion.notice_id)
            .join(SourceSite, SourceSite.id == TenderNotice.source_site_id)
            .where(NoticeVersion.raw_document_id == raw_document_id)
            .order_by(
                NoticeVersion.is_current.desc(),
                NoticeVersion.version_no.desc(),
                NoticeVersion.id.desc(),
            )
        ).first()
        if row is None:
            return None, None

        version: NoticeVersion = row[0]
        notice: TenderNotice = row[1]
        notice_source_code: str = row[2]

        return (
            CrawlErrorNoticeSummaryRecord(
                id=int(notice.id),
                source_code=notice_source_code,
                title=notice.title,
                notice_type=notice.notice_type,
                current_version_id=int(notice.current_version_id) if notice.current_version_id is not None else None,
            ),
            CrawlErrorNoticeVersionSummaryRecord(
                id=int(version.id),
                notice_id=int(version.notice_id),
                version_no=int(version.version_no),
                is_current=bool(version.is_current),
                title=version.title,
                notice_type=version.notice_type,
            ),
        )
