from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import CrawlJob, SourceSite
from app.services.crawl_job_payloads import build_runtime_stats_payload
from app.services.source_adapter_registry import normalize_source_code

CRAWL_JOB_TYPES = {"manual", "scheduled", "backfill", "manual_retry"}
CRAWL_JOB_STATUSES = {"pending", "running", "succeeded", "failed", "partial"}
CRAWL_JOB_FINAL_STATUSES = {"succeeded", "failed", "partial"}
ACTIVE_CRAWL_JOB_STATUSES = {"pending", "running"}
DEFAULT_PENDING_LEASE_SECONDS = 120
DEFAULT_RUNNING_LEASE_SECONDS = 1800
_UNSET = object()

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "failed"},
    "running": {"succeeded", "failed", "partial"},
    "succeeded": {"succeeded"},
    "failed": {"failed"},
    "partial": {"partial"},
}


@dataclass(slots=True)
class CrawlJobSnapshot:
    id: int
    source_site_id: int
    job_type: str
    status: str
    triggered_by: str | None
    retry_of_job_id: int | None
    queued_at: datetime | None
    picked_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    timeout_at: datetime | None
    lease_expires_at: datetime | None
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
    job_params_json: dict[str, Any] | None
    runtime_stats_json: dict[str, Any] | None
    failure_reason: str | None
    message: str | None


class CrawlJobService:
    """Manage crawl_job lifecycle and metric updates."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        engine=None,
    ) -> None:
        self.session_factory = session_factory
        self._owned_engine = engine

    @classmethod
    def from_database_url(cls, database_url: str) -> "CrawlJobService":
        engine = create_engine(database_url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        return cls(session_factory=session_factory, engine=engine)

    def close(self) -> None:
        if self._owned_engine is not None:
            self._owned_engine.dispose()
            self._owned_engine = None

    def create_job(
        self,
        *,
        source_code: str,
        source_name: str | None = None,
        source_url: str | None = None,
        job_type: str = "manual",
        triggered_by: str | None = None,
        retry_of_job_id: int | None = None,
        job_params_json: dict[str, Any] | None = None,
        runtime_stats_json: dict[str, Any] | None = None,
        failure_reason: str | None = None,
        message: str | None = None,
    ) -> CrawlJobSnapshot:
        with self.session_factory() as session:
            job = self.create_job_in_session(
                session,
                source_code=source_code,
                source_name=source_name,
                source_url=source_url,
                job_type=job_type,
                triggered_by=triggered_by,
                retry_of_job_id=retry_of_job_id,
                job_params_json=job_params_json,
                runtime_stats_json=runtime_stats_json,
                failure_reason=failure_reason,
                message=message,
            )
            session.commit()
            return _snapshot(job)

    def start_job(
        self,
        job_id: int,
        *,
        started_at: datetime | None = None,
        job_params_json: dict[str, Any] | None | object = _UNSET,
        runtime_stats_json: dict[str, Any] | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        message: str | None = None,
        lease_seconds: int = DEFAULT_RUNNING_LEASE_SECONDS,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.start_job_in_session(
                session,
                job_id=job_id,
                started_at=started_at,
                job_params_json=job_params_json,
                runtime_stats_json=runtime_stats_json,
                failure_reason=failure_reason,
                message=message,
                lease_seconds=lease_seconds,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

    def heartbeat_job(
        self,
        job_id: int,
        *,
        heartbeat_at: datetime | None = None,
        lease_seconds: int = DEFAULT_RUNNING_LEASE_SECONDS,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.heartbeat_job_in_session(
                session,
                job_id=job_id,
                heartbeat_at=heartbeat_at,
                lease_seconds=lease_seconds,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

    def record_stats(
        self,
        job_id: int,
        *,
        pages_fetched: int = 0,
        documents_saved: int = 0,
        notices_upserted: int = 0,
        deduplicated_count: int = 0,
        error_count: int = 0,
        list_items_seen: int = 0,
        list_items_unique: int = 0,
        list_items_source_duplicates_skipped: int = 0,
        detail_pages_fetched: int = 0,
        records_inserted: int = 0,
        records_updated: int = 0,
        source_duplicates_suppressed: int = 0,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.record_stats_in_session(
                session,
                job_id=job_id,
                pages_fetched=pages_fetched,
                documents_saved=documents_saved,
                notices_upserted=notices_upserted,
                deduplicated_count=deduplicated_count,
                error_count=error_count,
                list_items_seen=list_items_seen,
                list_items_unique=list_items_unique,
                list_items_source_duplicates_skipped=list_items_source_duplicates_skipped,
                detail_pages_fetched=detail_pages_fetched,
                records_inserted=records_inserted,
                records_updated=records_updated,
                source_duplicates_suppressed=source_duplicates_suppressed,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

    def claim_pending_job(
        self,
        job_id: int,
        *,
        picked_at: datetime | None = None,
        lease_seconds: int = DEFAULT_PENDING_LEASE_SECONDS,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.claim_pending_job_in_session(
                session,
                job_id=job_id,
                picked_at=picked_at,
                lease_seconds=lease_seconds,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

    def finish_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        job_params_json: dict[str, Any] | None | object = _UNSET,
        runtime_stats_json: dict[str, Any] | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        message: str | None = None,
        finished_at: datetime | None = None,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.finish_job_in_session(
                session,
                job_id=job_id,
                status=status,
                job_params_json=job_params_json,
                runtime_stats_json=runtime_stats_json,
                failure_reason=failure_reason,
                message=message,
                finished_at=finished_at,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

    def fail_job_if_active(
        self,
        job_id: int,
        *,
        job_params_json: dict[str, Any] | None | object = _UNSET,
        runtime_stats_json: dict[str, Any] | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        message: str | None,
        finished_at: datetime | None = None,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.fail_job_if_active_in_session(
                session,
                job_id=job_id,
                job_params_json=job_params_json,
                runtime_stats_json=runtime_stats_json,
                failure_reason=failure_reason,
                message=message,
                finished_at=finished_at,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

    def reconcile_expired_jobs(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[CrawlJobSnapshot]:
        with self.session_factory() as session:
            jobs = reconcile_expired_jobs_in_session(session, now=now, limit=limit)
            if jobs:
                session.commit()
            return [_snapshot(job) for job in jobs]

    def get_job(self, job_id: int) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                return None
            return _snapshot(job)

    def create_job_in_session(
        self,
        session: Session,
        *,
        source_code: str,
        source_name: str | None = None,
        source_url: str | None = None,
        job_type: str = "manual",
        triggered_by: str | None = None,
        retry_of_job_id: int | None = None,
        job_params_json: dict[str, Any] | None = None,
        runtime_stats_json: dict[str, Any] | None = None,
        failure_reason: str | None = None,
        message: str | None = None,
    ) -> CrawlJob:
        normalized_job_type = _normalize_job_type(job_type)
        source = _ensure_source_site(
            session,
            source_code=source_code,
            source_name=source_name,
            source_url=source_url,
        )
        normalized_retry_of_job_id = int(retry_of_job_id) if retry_of_job_id is not None else None
        if normalized_retry_of_job_id is not None:
            original_job = session.get(CrawlJob, normalized_retry_of_job_id)
            if original_job is None:
                raise ValueError(f"retry_of_job_id not found: {normalized_retry_of_job_id}")
        now = datetime.now(timezone.utc)
        job = CrawlJob(
            **_model_create_kwargs(
                session,
                CrawlJob,
                source_site_id=source.id,
                job_type=normalized_job_type,
                status="pending",
                triggered_by=_as_str(triggered_by),
                retry_of_job_id=normalized_retry_of_job_id,
                queued_at=now,
                picked_at=None,
                started_at=None,
                finished_at=None,
                heartbeat_at=None,
                timeout_at=None,
                lease_expires_at=None,
                pages_fetched=0,
                documents_saved=0,
                notices_upserted=0,
                deduplicated_count=0,
                error_count=0,
                list_items_seen=0,
                list_items_unique=0,
                list_items_source_duplicates_skipped=0,
                detail_pages_fetched=0,
                records_inserted=0,
                records_updated=0,
                source_duplicates_suppressed=0,
                job_params_json=_copy_json_payload(job_params_json),
                runtime_stats_json=_copy_json_payload(runtime_stats_json),
                failure_reason=_as_str(failure_reason),
                message=_as_str(message),
            )
        )
        session.add(job)
        session.flush()
        return job

    def claim_pending_job_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        picked_at: datetime | None = None,
        lease_seconds: int = DEFAULT_PENDING_LEASE_SECONDS,
    ) -> CrawlJob | None:
        moment = picked_at or datetime.now(timezone.utc)
        pending_timeout_at = _calculate_lease_expires_at(moment, lease_seconds=lease_seconds)
        timeout_expr = func.coalesce(CrawlJob.timeout_at, CrawlJob.lease_expires_at)
        result = session.execute(
            update(CrawlJob)
            .where(
                CrawlJob.id == int(job_id),
                CrawlJob.status == "pending",
                or_(
                    CrawlJob.picked_at.is_(None),
                    timeout_expr.is_(None),
                    timeout_expr <= moment,
                ),
            )
            .values(
                picked_at=moment,
                heartbeat_at=moment,
                timeout_at=pending_timeout_at,
                lease_expires_at=pending_timeout_at,
            )
        )
        if int(result.rowcount or 0) <= 0:
            return None
        return session.get(CrawlJob, int(job_id))

    def start_job_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        started_at: datetime | None = None,
        job_params_json: dict[str, Any] | None | object = _UNSET,
        runtime_stats_json: dict[str, Any] | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        message: str | None = None,
        lease_seconds: int = DEFAULT_RUNNING_LEASE_SECONDS,
    ) -> CrawlJob | None:
        now = datetime.now(timezone.utc)
        moment = started_at or now
        lease_anchor = now
        running_timeout_at = _calculate_lease_expires_at(lease_anchor, lease_seconds=lease_seconds)

        normalized_message = _as_str(message)
        values: dict[str, Any] = {
            "picked_at": func.coalesce(CrawlJob.picked_at, moment),
            "started_at": func.coalesce(CrawlJob.started_at, moment),
            "finished_at": None,
            "status": "running",
            "heartbeat_at": lease_anchor,
            "timeout_at": running_timeout_at,
            "lease_expires_at": running_timeout_at,
        }
        if normalized_message is not None:
            values["message"] = normalized_message
        if job_params_json is not _UNSET:
            values["job_params_json"] = _copy_json_payload(job_params_json)
        if runtime_stats_json is not _UNSET:
            values["runtime_stats_json"] = _copy_json_payload(runtime_stats_json)
        if failure_reason is not _UNSET:
            values["failure_reason"] = _as_str(failure_reason)

        started_job_id = (
            session.execute(
                update(CrawlJob)
                .where(
                    CrawlJob.id == int(job_id),
                    CrawlJob.status == "pending",
                )
                .values(**values)
                .returning(CrawlJob.id)
            )
            .scalar_one_or_none()
        )
        if started_job_id is None:
            return None

        session.expire_all()
        return session.get(CrawlJob, int(started_job_id))

    def heartbeat_job_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        heartbeat_at: datetime | None = None,
        lease_seconds: int = DEFAULT_RUNNING_LEASE_SECONDS,
    ) -> CrawlJob | None:
        job = session.get(CrawlJob, job_id)
        if job is None:
            return None
        if job.status not in ACTIVE_CRAWL_JOB_STATUSES:
            return job

        moment = heartbeat_at or datetime.now(timezone.utc)
        running_timeout_at = _calculate_lease_expires_at(moment, lease_seconds=lease_seconds)
        if job.picked_at is None:
            job.picked_at = moment
        if job.started_at is None and job.status == "running":
            job.started_at = moment
        job.heartbeat_at = moment
        job.timeout_at = running_timeout_at
        job.lease_expires_at = running_timeout_at
        return job

    def record_stats_in_session(
        self,
        session: Session,
        *,
        job_id: int | None,
        pages_fetched: int = 0,
        documents_saved: int = 0,
        notices_upserted: int = 0,
        deduplicated_count: int = 0,
        error_count: int = 0,
        list_items_seen: int = 0,
        list_items_unique: int = 0,
        list_items_source_duplicates_skipped: int = 0,
        detail_pages_fetched: int = 0,
        records_inserted: int = 0,
        records_updated: int = 0,
        source_duplicates_suppressed: int = 0,
    ) -> CrawlJob | None:
        if job_id is None:
            return None

        deltas = {
            "pages_fetched": _normalize_non_negative_delta(pages_fetched, field_name="pages_fetched"),
            "documents_saved": _normalize_non_negative_delta(documents_saved, field_name="documents_saved"),
            "notices_upserted": _normalize_non_negative_delta(notices_upserted, field_name="notices_upserted"),
            "deduplicated_count": _normalize_non_negative_delta(deduplicated_count, field_name="deduplicated_count"),
            "error_count": _normalize_non_negative_delta(error_count, field_name="error_count"),
            "list_items_seen": _normalize_non_negative_delta(list_items_seen, field_name="list_items_seen"),
            "list_items_unique": _normalize_non_negative_delta(list_items_unique, field_name="list_items_unique"),
            "list_items_source_duplicates_skipped": _normalize_non_negative_delta(
                list_items_source_duplicates_skipped,
                field_name="list_items_source_duplicates_skipped",
            ),
            "detail_pages_fetched": _normalize_non_negative_delta(
                detail_pages_fetched,
                field_name="detail_pages_fetched",
            ),
            "records_inserted": _normalize_non_negative_delta(records_inserted, field_name="records_inserted"),
            "records_updated": _normalize_non_negative_delta(records_updated, field_name="records_updated"),
            "source_duplicates_suppressed": _normalize_non_negative_delta(
                source_duplicates_suppressed,
                field_name="source_duplicates_suppressed",
            ),
        }
        if not any(deltas.values()):
            return session.get(CrawlJob, job_id)

        job = session.get(CrawlJob, job_id)
        if job is None:
            return None

        job.pages_fetched += deltas["pages_fetched"]
        job.documents_saved += deltas["documents_saved"]
        job.notices_upserted += deltas["notices_upserted"]
        job.deduplicated_count += deltas["deduplicated_count"]
        job.error_count += deltas["error_count"]
        job.list_items_seen += deltas["list_items_seen"]
        job.list_items_unique += deltas["list_items_unique"]
        job.list_items_source_duplicates_skipped += deltas["list_items_source_duplicates_skipped"]
        job.detail_pages_fetched += deltas["detail_pages_fetched"]
        job.records_inserted += deltas["records_inserted"]
        job.records_updated += deltas["records_updated"]
        job.source_duplicates_suppressed += deltas["source_duplicates_suppressed"]
        return job

    def finish_job_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        status: str | None = None,
        job_params_json: dict[str, Any] | None | object = _UNSET,
        runtime_stats_json: dict[str, Any] | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        message: str | None = None,
        finished_at: datetime | None = None,
    ) -> CrawlJob | None:
        job = session.get(CrawlJob, job_id)
        if job is None:
            return None

        target_status = _normalize_status(status) if status else self._infer_success_status(job)
        if target_status not in CRAWL_JOB_FINAL_STATUSES:
            raise ValueError(f"finish_job requires final status, got: {target_status}")

        _ensure_transition(job.status, target_status)

        now = finished_at or datetime.now(timezone.utc)
        if job.status == "running" and job.picked_at is None:
            job.picked_at = job.started_at or now
        if job.started_at is None:
            job.started_at = job.picked_at or job.created_at or now
        job.finished_at = now
        job.status = target_status
        job.heartbeat_at = now
        job.timeout_at = None
        job.lease_expires_at = None

        normalized_message = _as_str(message)
        if normalized_message is not None:
            job.message = normalized_message
        if job_params_json is not _UNSET:
            job.job_params_json = _copy_json_payload(job_params_json)
        if runtime_stats_json is not _UNSET:
            job.runtime_stats_json = _copy_json_payload(runtime_stats_json)
        if failure_reason is not _UNSET:
            job.failure_reason = _as_str(failure_reason)
        return job

    def fail_job_if_active_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        job_params_json: dict[str, Any] | None | object = _UNSET,
        runtime_stats_json: dict[str, Any] | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
        message: str | None,
        finished_at: datetime | None = None,
    ) -> CrawlJob | None:
        job = session.get(CrawlJob, job_id)
        if job is None:
            return None
        if job.status in CRAWL_JOB_FINAL_STATUSES:
            return job
        return self.finish_job_in_session(
            session,
            job_id=job_id,
            status="failed",
            job_params_json=job_params_json,
            runtime_stats_json=runtime_stats_json,
            failure_reason=failure_reason,
            message=message,
            finished_at=finished_at,
        )

    def _infer_success_status(self, job: CrawlJob) -> str:
        return "partial" if job.error_count > 0 else "succeeded"


def reconcile_expired_jobs_in_session(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[CrawlJob]:
    moment = now or datetime.now(timezone.utc)
    timeout_expr = func.coalesce(CrawlJob.timeout_at, CrawlJob.lease_expires_at)
    stmt = (
        select(CrawlJob)
        .where(
            CrawlJob.status == "running",
            timeout_expr.is_not(None),
            timeout_expr <= moment,
        )
        .order_by(timeout_expr.asc(), CrawlJob.id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    jobs = session.scalars(stmt).all()
    for job in jobs:
        _expire_job(job, now=moment)
    return jobs


def _ensure_source_site(
    session: Session,
    *,
    source_code: str,
    source_name: str | None,
    source_url: str | None,
) -> SourceSite:
    raw_code = _as_str(source_code)
    if not raw_code:
        raise ValueError("source_code is required")
    code = normalize_source_code(raw_code)

    source = session.scalar(select(SourceSite).where(SourceSite.code == code))
    if source is None and raw_code != code:
        source = session.scalar(select(SourceSite).where(SourceSite.code == raw_code))
    if source is None and code == "ggzy_gov_cn_deal":
        source = session.scalar(
            select(SourceSite)
            .where(SourceSite.code.in_(["2", "ggzy_gov_cn"]))
            .order_by(SourceSite.id.asc())
            .limit(1)
        )
        if source is None:
            source = session.scalar(
                select(SourceSite)
                .where(SourceSite.name.like("%全国公共资源交易平台%"))
                .order_by(SourceSite.id.asc())
                .limit(1)
            )
    if source is not None:
        if source.code != code:
            existing_target = session.scalar(select(SourceSite.id).where(SourceSite.code == code))
            if existing_target is None:
                source.code = code
        return source

    source = SourceSite(
        **_model_create_kwargs(
            session,
            SourceSite,
            code=code,
            name=_as_str(source_name) or code,
            base_url=_as_str(source_url) or "https://example.com",
            official_url=_as_str(source_url) or "https://example.com",
            list_url=_as_str(source_url) or "https://example.com",
            description="auto-created by crawl job service",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
    )
    session.add(source)
    session.flush()
    return source


def _ensure_transition(current_status: str, next_status: str) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current_status)
    if allowed is None:
        raise ValueError(f"unknown current crawl job status: {current_status}")
    if next_status not in allowed:
        raise ValueError(f"invalid crawl job status transition: {current_status} -> {next_status}")


def _expire_job(job: CrawlJob, *, now: datetime) -> None:
    original_status = str(job.status)
    previous_heartbeat_at = job.heartbeat_at
    previous_timeout_at = _resolve_timeout_at(job)
    failure_reason = _build_expired_job_failure_reason(stage=original_status)
    _ensure_transition(original_status, "failed")
    job.started_at = job.started_at or job.picked_at or job.created_at or now
    job.finished_at = now
    job.status = "failed"
    job.heartbeat_at = now
    job.timeout_at = None
    job.lease_expires_at = None
    job.failure_reason = failure_reason
    job.runtime_stats_json = build_runtime_stats_payload(
        run_stage="expired",
        timeout_stage=original_status,
        heartbeat_at=previous_heartbeat_at,
        timeout_at=previous_timeout_at,
    )
    job.message = _build_expired_job_message(stage=original_status, failure_reason=failure_reason)


def _build_expired_job_failure_reason(*, stage: str) -> str:
    if stage == "pending":
        return "任务启动超时，后台执行未在租约内启动"
    return "任务心跳超时，执行进程可能已退出或卡死"


def _build_expired_job_message(*, stage: str, failure_reason: str) -> str:
    if stage == "pending":
        return f"任务已放弃启动：{failure_reason}"
    return f"任务执行超时：{failure_reason}"


def _calculate_lease_expires_at(moment: datetime, *, lease_seconds: int) -> datetime:
    normalized_seconds = int(lease_seconds)
    if normalized_seconds < 1:
        raise ValueError("lease_seconds must be >= 1")
    return moment + timedelta(seconds=normalized_seconds)


def _normalize_job_type(value: str) -> str:
    normalized = _as_str(value)
    if not normalized:
        raise ValueError("job_type is required")
    if normalized not in CRAWL_JOB_TYPES:
        raise ValueError(f"unsupported crawl job type: {normalized}")
    return normalized


def _normalize_status(value: str) -> str:
    normalized = _as_str(value)
    if not normalized:
        raise ValueError("status is required")
    if normalized not in CRAWL_JOB_STATUSES:
        raise ValueError(f"unsupported crawl job status: {normalized}")
    return normalized


def _normalize_non_negative_delta(value: int, *, field_name: str) -> int:
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return int(value)


def _snapshot(job: CrawlJob) -> CrawlJobSnapshot:
    return CrawlJobSnapshot(
        id=int(job.id),
        source_site_id=int(job.source_site_id),
        job_type=job.job_type,
        status=job.status,
        triggered_by=job.triggered_by,
        retry_of_job_id=int(job.retry_of_job_id) if job.retry_of_job_id is not None else None,
        queued_at=job.queued_at,
        picked_at=job.picked_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
        timeout_at=_resolve_timeout_at(job),
        lease_expires_at=job.lease_expires_at,
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
        job_params_json=_copy_json_payload(job.job_params_json),
        runtime_stats_json=_copy_json_payload(job.runtime_stats_json),
        failure_reason=job.failure_reason,
        message=job.message,
    )


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _append_message(existing: str | None, extra: str | None) -> str | None:
    normalized_existing = _as_str(existing)
    normalized_extra = _as_str(extra)
    if normalized_existing and normalized_extra:
        return f"{normalized_existing}; {normalized_extra}"
    return normalized_existing or normalized_extra


def _copy_json_payload(value: object) -> dict[str, Any] | None:
    if value is None or value is _UNSET:
        return None
    if not isinstance(value, dict):
        raise ValueError("crawl job json payload must be a dict")
    return dict(value)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _resolve_timeout_at(job: CrawlJob) -> datetime | None:
    return job.timeout_at or job.lease_expires_at


def _model_create_kwargs(session: Session, model_cls: type, **kwargs: Any) -> dict[str, Any]:
    if not _is_sqlite(session):
        return kwargs
    if "id" in kwargs and kwargs["id"] is not None:
        return kwargs

    next_id = session.scalar(select(func.max(model_cls.id)))
    payload = dict(kwargs)
    payload["id"] = (next_id or 0) + 1
    return payload


def _is_sqlite(session: Session) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    return bind.dialect.name == "sqlite"
