from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CrawlError, CrawlJob, NoticeVersion, RawDocument, SourceSite, TenderNotice


@dataclass(slots=True)
class DailyCountRecord:
    date: str
    count: int


@dataclass(slots=True)
class RecentJobSummaryRecord:
    id: int
    source_code: str
    status: str
    job_type: str
    started_at: datetime | None
    finished_at: datetime | None
    error_count: int
    message: str | None


@dataclass(slots=True)
class RecentCrawlErrorSummaryRecord:
    id: int
    source_code: str
    crawl_job_id: int | None
    stage: str
    error_type: str
    message: str
    url: str | None
    created_at: datetime


@dataclass(slots=True)
class StatsOverviewRecord:
    source_count: int
    active_source_count: int
    crawl_job_count: int
    crawl_job_running_count: int
    notice_count: int
    today_new_notice_count: int
    recent_24h_new_notice_count: int
    raw_document_count: int
    crawl_error_count: int
    recent_7d_crawl_job_counts: list[DailyCountRecord]
    recent_7d_notice_counts: list[DailyCountRecord]
    recent_7d_crawl_error_counts: list[DailyCountRecord]
    recent_failed_or_partial_jobs: list[RecentJobSummaryRecord]
    recent_crawl_errors: list[RecentCrawlErrorSummaryRecord]


class StatsRepository:
    """SQLAlchemy repository for dashboard/overview statistics."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_overview(
        self,
        *,
        recent_days: int = 7,
        recent_failed_job_limit: int = 10,
        recent_error_limit: int = 10,
    ) -> StatsOverviewRecord:
        from app.services.crawl_job_service import reconcile_expired_jobs_in_session

        expired_jobs = reconcile_expired_jobs_in_session(self.session)
        if expired_jobs:
            self.session.commit()
        return StatsOverviewRecord(
            source_count=int(self.session.scalar(select(func.count(SourceSite.id))) or 0),
            active_source_count=int(
                self.session.scalar(select(func.count(SourceSite.id)).where(SourceSite.is_active.is_(True))) or 0
            ),
            crawl_job_count=int(self.session.scalar(select(func.count(CrawlJob.id))) or 0),
            crawl_job_running_count=int(
                self.session.scalar(
                    select(func.count(CrawlJob.id)).where(CrawlJob.status == "running")
                )
                or 0
            ),
            notice_count=int(self.session.scalar(select(func.count(TenderNotice.id))) or 0),
            today_new_notice_count=self._count_recent_notice_updates(
                start_at=datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
            ),
            recent_24h_new_notice_count=self._count_recent_notice_updates(
                start_at=datetime.now(timezone.utc) - timedelta(hours=24)
            ),
            raw_document_count=int(self.session.scalar(select(func.count(RawDocument.id))) or 0),
            crawl_error_count=int(self.session.scalar(select(func.count(CrawlError.id))) or 0),
            recent_7d_crawl_job_counts=self._get_recent_daily_counts(
                model=CrawlJob,
                datetime_column=CrawlJob.created_at,
                recent_days=recent_days,
            ),
            recent_7d_notice_counts=self._get_recent_daily_counts(
                model=TenderNotice,
                datetime_column=TenderNotice.created_at,
                recent_days=recent_days,
            ),
            recent_7d_crawl_error_counts=self._get_recent_daily_counts(
                model=CrawlError,
                datetime_column=CrawlError.created_at,
                recent_days=recent_days,
            ),
            recent_failed_or_partial_jobs=self._get_recent_failed_or_partial_jobs(limit=recent_failed_job_limit),
            recent_crawl_errors=self._get_recent_crawl_errors(limit=recent_error_limit),
        )

    def _get_recent_daily_counts(
        self,
        *,
        model: type,
        datetime_column,
        recent_days: int,
    ) -> list[DailyCountRecord]:
        today = datetime.now(timezone.utc).date()
        start_day = today - timedelta(days=recent_days - 1)
        start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)

        grouped = self.session.execute(
            select(func.date(datetime_column), func.count())
            .select_from(model)
            .where(datetime_column >= start_at)
            .group_by(func.date(datetime_column))
        ).all()

        count_map: dict[str, int] = {}
        for day_value, count in grouped:
            normalized_day = self._to_iso_date(day_value)
            if normalized_day is None:
                continue
            count_map[normalized_day] = int(count or 0)

        return [
            DailyCountRecord(
                date=(start_day + timedelta(days=offset)).isoformat(),
                count=count_map.get((start_day + timedelta(days=offset)).isoformat(), 0),
            )
            for offset in range(recent_days)
        ]

    def _get_recent_failed_or_partial_jobs(self, *, limit: int) -> list[RecentJobSummaryRecord]:
        rows = self.session.execute(
            select(CrawlJob, SourceSite.code)
            .join(SourceSite, SourceSite.id == CrawlJob.source_site_id)
            .where(CrawlJob.status.in_(["failed", "partial"]))
            .order_by(CrawlJob.created_at.desc(), CrawlJob.id.desc())
            .limit(limit)
        ).all()

        return [
            RecentJobSummaryRecord(
                id=int(job.id),
                source_code=source_code,
                status=job.status,
                job_type=job.job_type,
                started_at=job.started_at,
                finished_at=job.finished_at,
                error_count=int(job.error_count or 0),
                message=job.message,
            )
            for job, source_code in rows
        ]

    def _get_recent_crawl_errors(self, *, limit: int) -> list[RecentCrawlErrorSummaryRecord]:
        rows = self.session.execute(
            select(CrawlError, SourceSite.code)
            .join(SourceSite, SourceSite.id == CrawlError.source_site_id)
            .order_by(CrawlError.created_at.desc(), CrawlError.id.desc())
            .limit(limit)
        ).all()

        return [
            RecentCrawlErrorSummaryRecord(
                id=int(error.id),
                source_code=source_code,
                crawl_job_id=int(error.crawl_job_id) if error.crawl_job_id is not None else None,
                stage=error.stage,
                error_type=error.error_type,
                message=error.error_message,
                url=error.url,
                created_at=error.created_at,
            )
            for error, source_code in rows
        ]

    def _count_recent_notice_updates(self, *, start_at: datetime) -> int:
        union_subquery = (
            select(TenderNotice.id.label("notice_id"))
            .where(TenderNotice.created_at >= start_at)
            .union(
                select(NoticeVersion.notice_id.label("notice_id"))
                .where(
                    NoticeVersion.notice_id.is_not(None),
                    NoticeVersion.created_at >= start_at,
                )
            )
            .subquery()
        )
        return int(self.session.scalar(select(func.count()).select_from(union_subquery)) or 0)

    def _to_iso_date(self, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        text = str(value)
        if not text:
            return None
        return text[:10]
