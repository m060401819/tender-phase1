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


@dataclass(slots=True)
class CrawlJobRecord:
    id: int
    source_site_id: int
    source_code: str
    job_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    pages_fetched: int
    documents_saved: int
    notices_upserted: int
    deduplicated_count: int
    error_count: int
    message: str | None
    recent_crawl_error_count: int | None = None


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

        return self._to_record(
            job=job,
            source_code=source_code,
            recent_crawl_error_count=recent_crawl_error_count,
        )

    def _build_base_query(self, filters: CrawlJobQueryFilters) -> Select:
        stmt = select(CrawlJob, SourceSite.code).join(SourceSite, SourceSite.id == CrawlJob.source_site_id)

        if filters.source_code:
            stmt = stmt.where(SourceSite.code == filters.source_code)
        if filters.status:
            stmt = stmt.where(CrawlJob.status == filters.status)
        if filters.job_type:
            stmt = stmt.where(CrawlJob.job_type == filters.job_type)
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
            started_at=job.started_at,
            finished_at=job.finished_at,
            pages_fetched=int(job.pages_fetched or 0),
            documents_saved=int(job.documents_saved or 0),
            notices_upserted=int(job.notices_upserted or 0),
            deduplicated_count=int(job.deduplicated_count or 0),
            error_count=int(job.error_count or 0),
            message=job.message,
            recent_crawl_error_count=recent_crawl_error_count,
        )
