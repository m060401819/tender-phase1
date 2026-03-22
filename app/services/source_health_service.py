from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import CrawlError, CrawlJob, SourceSite
from app.services.health_rule_service import HealthRuleService

HEALTH_STATUS_LABELS = {
    "normal": "正常",
    "warning": "警告",
    "critical": "异常",
}

JOB_STATUS_LABELS = {
    "pending": "等待中",
    "running": "进行中",
    "succeeded": "成功",
    "failed": "失败",
    "partial": "部分成功",
}


@dataclass(slots=True)
class SourceHealthSummary:
    source_id: int
    source_code: str
    health_status: str
    health_status_label: str
    latest_job_id: int | None
    latest_job_status: str | None
    latest_job_status_label: str
    latest_job_started_at: datetime | None
    latest_notices_upserted: int
    latest_error_count: int
    latest_list_items_seen: int
    latest_list_items_unique: int
    latest_list_items_source_duplicates_skipped: int
    latest_detail_pages_fetched: int
    latest_source_duplicates_suppressed: int
    recent_7d_job_count: int
    recent_7d_failed_count: int
    recent_7d_error_count: int
    consecutive_failed: bool
    latest_failure_reason: str


class SourceHealthService:
    """Compute lightweight source health summary for operations pages."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_source_health_by_code(self, code: str) -> SourceHealthSummary | None:
        source = self.session.scalar(select(SourceSite).where(SourceSite.code == code))
        if source is None:
            return None
        summary_map = self.build_health_map([(int(source.id), source.code)])
        return summary_map.get(int(source.id))

    def build_health_map(self, sources: list[tuple[int, str]]) -> dict[int, SourceHealthSummary]:
        if not sources:
            return {}

        source_ids = [source_id for source_id, _ in sources]
        source_code_map = {source_id: source_code for source_id, source_code in sources}
        rules = HealthRuleService(self.session).get_rules()

        latest_job_map = self._latest_job_map(source_ids)
        recent_7d_job_stats = self._recent_7d_job_stats(source_ids)
        recent_7d_error_count_map = self._recent_7d_error_count_map(source_ids)
        latest_error_reason_map = self._latest_error_reason_map(source_ids)
        latest_failed_job_reason_map = self._latest_failed_job_reason_map(source_ids)

        result: dict[int, SourceHealthSummary] = {}
        for source_id in source_ids:
            latest_job = latest_job_map.get(source_id)
            latest_status = latest_job.status if latest_job is not None else None
            consecutive_failure_count = self._consecutive_failure_count(source_id)
            consecutive_failed = consecutive_failure_count >= 2

            recent_job_count, recent_failed_count = recent_7d_job_stats.get(source_id, (0, 0))
            recent_error_count = recent_7d_error_count_map.get(source_id, 0)
            health_status = HealthRuleService.evaluate_health_status(
                rules=rules,
                latest_status=latest_status,
                consecutive_failure_count=consecutive_failure_count,
                recent_7d_error_count=recent_error_count,
            )

            failure_reason = latest_error_reason_map.get(source_id)
            if not failure_reason:
                failure_reason = latest_failed_job_reason_map.get(source_id)
            if not failure_reason and latest_job is not None and latest_job.message:
                failure_reason = latest_job.message

            result[source_id] = SourceHealthSummary(
                source_id=source_id,
                source_code=source_code_map[source_id],
                health_status=health_status,
                health_status_label=HEALTH_STATUS_LABELS[health_status],
                latest_job_id=int(latest_job.id) if latest_job is not None else None,
                latest_job_status=latest_status,
                latest_job_status_label=JOB_STATUS_LABELS.get(latest_status or "", "-") if latest_status else "-",
                latest_job_started_at=latest_job.started_at if latest_job is not None else None,
                latest_notices_upserted=int(latest_job.notices_upserted or 0) if latest_job is not None else 0,
                latest_error_count=int(latest_job.error_count or 0) if latest_job is not None else 0,
                latest_list_items_seen=int(latest_job.list_items_seen or 0) if latest_job is not None else 0,
                latest_list_items_unique=int(latest_job.list_items_unique or 0) if latest_job is not None else 0,
                latest_list_items_source_duplicates_skipped=(
                    int(latest_job.list_items_source_duplicates_skipped or 0) if latest_job is not None else 0
                ),
                latest_detail_pages_fetched=int(latest_job.detail_pages_fetched or 0) if latest_job is not None else 0,
                latest_source_duplicates_suppressed=(
                    int(latest_job.source_duplicates_suppressed or 0) if latest_job is not None else 0
                ),
                recent_7d_job_count=int(recent_job_count),
                recent_7d_failed_count=int(recent_failed_count),
                recent_7d_error_count=int(recent_error_count),
                consecutive_failed=consecutive_failed,
                latest_failure_reason=failure_reason or "-",
            )
        return result

    def _latest_job_map(self, source_ids: list[int]) -> dict[int, CrawlJob]:
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
            select(CrawlJob).join(latest_job_subquery, CrawlJob.id == latest_job_subquery.c.latest_job_id)
        ).scalars().all()
        return {int(item.source_site_id): item for item in rows}

    def _recent_7d_job_stats(self, source_ids: list[int]) -> dict[int, tuple[int, int]]:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        rows = self.session.execute(
            select(
                CrawlJob.source_site_id,
                func.count(CrawlJob.id).label("job_count"),
                func.coalesce(
                    func.sum(case((CrawlJob.status == "failed", 1), else_=0)),
                    0,
                ).label("failed_count"),
            )
            .where(
                CrawlJob.source_site_id.in_(source_ids),
                CrawlJob.created_at >= since,
            )
            .group_by(CrawlJob.source_site_id)
        ).all()
        return {int(source_site_id): (int(job_count or 0), int(failed_count or 0)) for source_site_id, job_count, failed_count in rows}

    def _recent_7d_error_count_map(self, source_ids: list[int]) -> dict[int, int]:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        rows = self.session.execute(
            select(
                CrawlError.source_site_id,
                func.count(CrawlError.id),
            )
            .where(
                CrawlError.source_site_id.in_(source_ids),
                CrawlError.created_at >= since,
            )
            .group_by(CrawlError.source_site_id)
        ).all()
        return {int(source_site_id): int(count or 0) for source_site_id, count in rows}

    def _latest_error_reason_map(self, source_ids: list[int]) -> dict[int, str]:
        result: dict[int, str] = {}
        for source_id in source_ids:
            message = self.session.scalar(
                select(CrawlError.error_message)
                .where(CrawlError.source_site_id == source_id)
                .order_by(CrawlError.created_at.desc(), CrawlError.id.desc())
                .limit(1)
            )
            if message is not None and str(message).strip():
                result[source_id] = str(message)
        return result

    def _latest_failed_job_reason_map(self, source_ids: list[int]) -> dict[int, str]:
        result: dict[int, str] = {}
        for source_id in source_ids:
            message = self.session.scalar(
                select(CrawlJob.message)
                .where(
                    CrawlJob.source_site_id == source_id,
                    CrawlJob.status.in_(["failed", "partial"]),
                )
                .order_by(CrawlJob.started_at.desc(), CrawlJob.id.desc())
                .limit(1)
            )
            if message is not None and str(message).strip():
                result[source_id] = str(message)
        return result

    def _consecutive_failure_count(self, source_id: int) -> int:
        statuses = self.session.scalars(
            select(CrawlJob.status)
            .where(CrawlJob.source_site_id == source_id)
            .order_by(CrawlJob.id.desc())
            .limit(10)
        ).all()
        count = 0
        for status in statuses:
            if status != "failed":
                break
            count += 1
        return count
