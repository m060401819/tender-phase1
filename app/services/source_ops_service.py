from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import CrawlError, CrawlJob, NoticeVersion, SourceSite, TenderNotice


@dataclass(slots=True)
class SourceOpsSummary:
    source_id: int
    source_code: str
    source_name: str
    official_url: str
    is_active: bool
    schedule_enabled: bool
    schedule_days: int
    today_crawl_job_count: int
    today_success_count: int
    today_failed_count: int
    today_partial_count: int
    today_new_notice_count: int
    last_job_status: str | None
    last_job_finished_at: datetime | None
    last_error_message: str | None
    last_retry_status: str | None
    last_retry_job_id: int | None


class SourceOpsService:
    """Aggregate lightweight source operations metrics for admin/report views."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_source_ops(
        self,
        *,
        recent_hours: int = 24,
        source_code: str | None = None,
        source_codes: list[str] | None = None,
    ) -> list[SourceOpsSummary]:
        if recent_hours < 1:
            raise ValueError("recent_hours must be >= 1")
        if source_codes is not None and len(source_codes) == 0:
            return []

        source_stmt = select(SourceSite)
        if source_code:
            source_stmt = source_stmt.where(SourceSite.code == source_code)
        if source_codes:
            source_stmt = source_stmt.where(SourceSite.code.in_(source_codes))
        sources = self.session.scalars(source_stmt.order_by(SourceSite.code.asc())).all()
        if not sources:
            return []

        source_ids = [int(source.id) for source in sources]
        since = datetime.now(timezone.utc) - timedelta(hours=recent_hours)

        job_stats_map = self._load_job_stats(source_ids=source_ids, since=since)
        notice_count_map = self._load_notice_counts(source_ids=source_ids, since=since)
        latest_job_map = self._load_latest_job_map(source_ids=source_ids)
        latest_error_map = self._load_latest_error_map(source_ids=source_ids)
        latest_retry_map = self._load_latest_retry_map(source_ids=source_ids)

        items: list[SourceOpsSummary] = []
        for source in sources:
            source_id = int(source.id)
            job_count, success_count, failed_count, partial_count = job_stats_map.get(source_id, (0, 0, 0, 0))
            last_job_status, last_job_finished_at = latest_job_map.get(source_id, (None, None))
            last_retry_status, last_retry_job_id = latest_retry_map.get(source_id, (None, None))
            items.append(
                SourceOpsSummary(
                    source_id=source_id,
                    source_code=source.code,
                    source_name=source.name,
                    official_url=source.official_url or source.base_url,
                    is_active=bool(source.is_active),
                    schedule_enabled=bool(source.schedule_enabled),
                    schedule_days=int(source.schedule_days),
                    today_crawl_job_count=int(job_count),
                    today_success_count=int(success_count),
                    today_failed_count=int(failed_count),
                    today_partial_count=int(partial_count),
                    today_new_notice_count=int(notice_count_map.get(source_id, 0)),
                    last_job_status=last_job_status,
                    last_job_finished_at=last_job_finished_at,
                    last_error_message=latest_error_map.get(source_id),
                    last_retry_status=last_retry_status,
                    last_retry_job_id=last_retry_job_id,
                )
            )
        return items

    def get_source_ops(
        self,
        *,
        source_code: str,
        recent_hours: int = 24,
    ) -> SourceOpsSummary | None:
        items = self.list_source_ops(recent_hours=recent_hours, source_code=source_code)
        if not items:
            return None
        return items[0]

    def _load_job_stats(
        self,
        *,
        source_ids: list[int],
        since: datetime,
    ) -> dict[int, tuple[int, int, int, int]]:
        rows = self.session.execute(
            select(
                CrawlJob.source_site_id,
                func.count(CrawlJob.id).label("job_count"),
                func.coalesce(func.sum(case((CrawlJob.status == "succeeded", 1), else_=0)), 0).label("success_count"),
                func.coalesce(func.sum(case((CrawlJob.status == "failed", 1), else_=0)), 0).label("failed_count"),
                func.coalesce(func.sum(case((CrawlJob.status == "partial", 1), else_=0)), 0).label("partial_count"),
            )
            .where(
                CrawlJob.source_site_id.in_(source_ids),
                CrawlJob.created_at >= since,
            )
            .group_by(CrawlJob.source_site_id)
        ).all()
        return {
            int(source_site_id): (
                int(job_count or 0),
                int(success_count or 0),
                int(failed_count or 0),
                int(partial_count or 0),
            )
            for source_site_id, job_count, success_count, failed_count, partial_count in rows
        }

    def _load_notice_counts(self, *, source_ids: list[int], since: datetime) -> dict[int, int]:
        notice_union = (
            select(
                TenderNotice.source_site_id.label("source_site_id"),
                TenderNotice.id.label("notice_id"),
            )
            .where(
                TenderNotice.source_site_id.in_(source_ids),
                TenderNotice.created_at >= since,
            )
            .union(
                select(
                    TenderNotice.source_site_id.label("source_site_id"),
                    NoticeVersion.notice_id.label("notice_id"),
                )
                .join(TenderNotice, TenderNotice.id == NoticeVersion.notice_id)
                .where(
                    TenderNotice.source_site_id.in_(source_ids),
                    NoticeVersion.notice_id.is_not(None),
                    NoticeVersion.created_at >= since,
                )
            )
            .subquery()
        )
        rows = self.session.execute(
            select(notice_union.c.source_site_id, func.count(func.distinct(notice_union.c.notice_id)))
            .group_by(notice_union.c.source_site_id)
        ).all()
        return {
            int(source_site_id): int(count or 0)
            for source_site_id, count in rows
        }

    def _load_latest_job_map(self, *, source_ids: list[int]) -> dict[int, tuple[str | None, datetime | None]]:
        latest_job_subquery = (
            select(
                CrawlJob.source_site_id.label("source_site_id"),
                func.max(CrawlJob.id).label("latest_job_id"),
            )
            .where(CrawlJob.source_site_id.in_(source_ids))
            .group_by(CrawlJob.source_site_id)
            .subquery()
        )
        rows = self.session.execute(
            select(CrawlJob.source_site_id, CrawlJob.status, CrawlJob.finished_at)
            .join(latest_job_subquery, CrawlJob.id == latest_job_subquery.c.latest_job_id)
        ).all()
        return {
            int(source_site_id): (status, finished_at)
            for source_site_id, status, finished_at in rows
        }

    def _load_latest_error_map(self, *, source_ids: list[int]) -> dict[int, str]:
        latest_error_subquery = (
            select(
                CrawlError.source_site_id.label("source_site_id"),
                func.max(CrawlError.id).label("latest_error_id"),
            )
            .where(CrawlError.source_site_id.in_(source_ids))
            .group_by(CrawlError.source_site_id)
            .subquery()
        )
        rows = self.session.execute(
            select(CrawlError.source_site_id, CrawlError.error_message)
            .join(latest_error_subquery, CrawlError.id == latest_error_subquery.c.latest_error_id)
        ).all()
        return {
            int(source_site_id): str(message)
            for source_site_id, message in rows
            if message is not None and str(message).strip()
        }

    def _load_latest_retry_map(self, *, source_ids: list[int]) -> dict[int, tuple[str | None, int | None]]:
        latest_retry_subquery = (
            select(
                CrawlJob.source_site_id.label("source_site_id"),
                func.max(CrawlJob.id).label("latest_retry_id"),
            )
            .where(
                CrawlJob.source_site_id.in_(source_ids),
                CrawlJob.retry_of_job_id.is_not(None),
            )
            .group_by(CrawlJob.source_site_id)
            .subquery()
        )
        rows = self.session.execute(
            select(CrawlJob.source_site_id, CrawlJob.status, CrawlJob.id)
            .join(latest_retry_subquery, CrawlJob.id == latest_retry_subquery.c.latest_retry_id)
        ).all()
        return {
            int(source_site_id): (status, int(job_id) if job_id is not None else None)
            for source_site_id, status, job_id in rows
        }
