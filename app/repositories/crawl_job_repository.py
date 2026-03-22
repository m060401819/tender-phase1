from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import CrawlError, CrawlJob, SourceSite

CrawlJobOrderBy = Literal["started_at", "id"]


@dataclass(slots=True)
class CrawlJobQueryFilters:
    source_code: str | None = None
    status: str | None = None
    job_type: str | None = None
    status_in: tuple[str, ...] | None = None
    started_from: datetime | None = None


@dataclass(slots=True)
class CrawlJobRecord:
    id: int
    source_site_id: int
    source_code: str
    job_type: str
    status: str
    retry_of_job_id: int | None
    retried_by_job_id: int | None
    retried_by_status: str | None
    retried_by_finished_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    pages_fetched: int
    documents_saved: int
    notices_upserted: int
    deduplicated_count: int
    error_count: int
    list_items_seen: int
    list_items_unique: int
    list_items_source_duplicates_skipped: int
    detail_pages_fetched: int
    records_inserted: int
    records_updated: int
    source_duplicates_suppressed: int
    message: str | None
    recent_crawl_error_count: int | None = None
    retry_of_job_status: str | None = None
    retry_of_job_message: str | None = None
    retried_by_message: str | None = None


@dataclass(slots=True)
class CrawlJobListResult:
    items: list[CrawlJobRecord]
    total: int
    limit: int
    offset: int
    order_by: CrawlJobOrderBy


class CrawlJobRepository:
    """SQLAlchemy repository for crawl_job querying."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_jobs(
        self,
        *,
        filters: CrawlJobQueryFilters,
        order_by: CrawlJobOrderBy = "started_at",
        limit: int = 20,
        offset: int = 0,
    ) -> CrawlJobListResult:
        base = self._build_base_query(filters)

        total_stmt = select(func.count()).select_from(base.subquery())
        total = int(self.session.scalar(total_stmt) or 0)

        if order_by == "started_at":
            base = base.order_by(
                CrawlJob.started_at.is_(None),
                CrawlJob.started_at.desc(),
                CrawlJob.id.desc(),
            )
        else:
            base = base.order_by(CrawlJob.id.desc())

        rows = self.session.execute(base.limit(limit).offset(offset)).all()
        items = [self._to_record(job=row[0], source_code=row[1]) for row in rows]
        self._attach_retry_info(items)

        return CrawlJobListResult(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            order_by=order_by,
        )

    def get_job_detail(self, job_id: int, *, recent_window_days: int = 7) -> CrawlJobRecord | None:
        row = self.session.execute(
            select(CrawlJob, SourceSite.code)
            .join(SourceSite, SourceSite.id == CrawlJob.source_site_id)
            .where(CrawlJob.id == job_id)
        ).first()
        if row is None:
            return None

        job: CrawlJob = row[0]
        source_code: str = row[1]

        recent_since = datetime.now(timezone.utc) - timedelta(days=recent_window_days)
        recent_crawl_error_count = int(
            self.session.scalar(
                select(func.count(CrawlError.id)).where(
                    CrawlError.crawl_job_id == job.id,
                    CrawlError.occurred_at >= recent_since,
                )
            )
            or 0
        )

        record = self._to_record(
            job=job,
            source_code=source_code,
            recent_crawl_error_count=recent_crawl_error_count,
        )
        self._attach_retry_info([record])
        return record

    def _attach_retry_info(self, items: list[CrawlJobRecord]) -> None:
        if not items:
            return
        original_ids = [item.id for item in items]
        retry_rows = self.session.execute(
            select(
                CrawlJob.retry_of_job_id,
                CrawlJob.id,
                CrawlJob.status,
                CrawlJob.finished_at,
                CrawlJob.message,
            )
            .where(CrawlJob.retry_of_job_id.in_(original_ids))
            .order_by(CrawlJob.id.desc())
        ).all()
        retry_map: dict[int, tuple[int, str, datetime | None, str | None]] = {}
        for retry_of_job_id, retry_job_id, retry_status, retry_finished_at, retry_message in retry_rows:
            if retry_of_job_id is None:
                continue
            key = int(retry_of_job_id)
            if key in retry_map:
                continue
            retry_map[key] = (
                int(retry_job_id),
                retry_status,
                retry_finished_at,
                retry_message,
            )

        for item in items:
            if item.retry_of_job_id is not None:
                original = self.session.get(CrawlJob, item.retry_of_job_id)
                if original is not None:
                    item.retry_of_job_status = original.status
                    item.retry_of_job_message = original.message
            retry_payload = retry_map.get(item.id)
            if retry_payload is None:
                continue
            item.retried_by_job_id = retry_payload[0]
            item.retried_by_status = retry_payload[1]
            item.retried_by_finished_at = retry_payload[2]
            item.retried_by_message = retry_payload[3]

    def _build_base_query(self, filters: CrawlJobQueryFilters) -> Select:
        stmt = select(CrawlJob, SourceSite.code).join(SourceSite, SourceSite.id == CrawlJob.source_site_id)

        if filters.source_code:
            stmt = stmt.where(SourceSite.code == filters.source_code)
        if filters.status:
            stmt = stmt.where(CrawlJob.status == filters.status)
        if filters.status_in:
            stmt = stmt.where(CrawlJob.status.in_(list(filters.status_in)))
        if filters.job_type:
            stmt = stmt.where(CrawlJob.job_type == filters.job_type)
        if filters.started_from is not None:
            stmt = stmt.where(CrawlJob.started_at >= filters.started_from)
        return stmt

    def _to_record(
        self,
        *,
        job: CrawlJob,
        source_code: str,
        recent_crawl_error_count: int | None = None,
    ) -> CrawlJobRecord:
        return CrawlJobRecord(
            id=int(job.id),
            source_site_id=int(job.source_site_id),
            source_code=source_code,
            job_type=job.job_type,
            status=job.status,
            retry_of_job_id=int(job.retry_of_job_id) if job.retry_of_job_id is not None else None,
            retried_by_job_id=None,
            retried_by_status=None,
            retried_by_finished_at=None,
            started_at=job.started_at,
            finished_at=job.finished_at,
            pages_fetched=int(job.pages_fetched or 0),
            documents_saved=int(job.documents_saved or 0),
            notices_upserted=int(job.notices_upserted or 0),
            deduplicated_count=int(job.deduplicated_count or 0),
            error_count=int(job.error_count or 0),
            list_items_seen=int(job.list_items_seen or 0),
            list_items_unique=int(job.list_items_unique or 0),
            list_items_source_duplicates_skipped=int(job.list_items_source_duplicates_skipped or 0),
            detail_pages_fetched=int(job.detail_pages_fetched or 0),
            records_inserted=int(job.records_inserted or 0),
            records_updated=int(job.records_updated or 0),
            source_duplicates_suppressed=int(job.source_duplicates_suppressed or 0),
            message=job.message,
            recent_crawl_error_count=recent_crawl_error_count,
        )
