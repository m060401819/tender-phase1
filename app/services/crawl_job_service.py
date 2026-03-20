from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CrawlJob, SourceSite

CRAWL_JOB_TYPES = {"manual", "scheduled", "backfill"}
CRAWL_JOB_STATUSES = {"pending", "running", "succeeded", "failed", "partial"}
CRAWL_JOB_FINAL_STATUSES = {"succeeded", "failed", "partial"}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"pending", "running", "failed"},
    "running": {"running", "succeeded", "failed", "partial"},
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
    started_at: datetime | None
    finished_at: datetime | None
    pages_fetched: int
    documents_saved: int
    notices_upserted: int
    deduplicated_count: int
    error_count: int
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
                message=message,
            )
            session.commit()
            return _snapshot(job)

    def start_job(
        self,
        job_id: int,
        *,
        started_at: datetime | None = None,
        message: str | None = None,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.start_job_in_session(session, job_id=job_id, started_at=started_at, message=message)
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
        message: str | None = None,
        finished_at: datetime | None = None,
    ) -> CrawlJobSnapshot | None:
        with self.session_factory() as session:
            job = self.finish_job_in_session(
                session,
                job_id=job_id,
                status=status,
                message=message,
                finished_at=finished_at,
            )
            if job is None:
                return None
            session.commit()
            return _snapshot(job)

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
        message: str | None = None,
    ) -> CrawlJob:
        normalized_job_type = _normalize_job_type(job_type)
        source = _ensure_source_site(
            session,
            source_code=source_code,
            source_name=source_name,
            source_url=source_url,
        )
        job = CrawlJob(
            **_model_create_kwargs(
                session,
                CrawlJob,
                source_site_id=source.id,
                job_type=normalized_job_type,
                status="pending",
                triggered_by=_as_str(triggered_by),
                started_at=None,
                finished_at=None,
                pages_fetched=0,
                documents_saved=0,
                notices_upserted=0,
                deduplicated_count=0,
                error_count=0,
                message=_as_str(message),
            )
        )
        session.add(job)
        session.flush()
        return job

    def start_job_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        started_at: datetime | None = None,
        message: str | None = None,
    ) -> CrawlJob | None:
        job = session.get(CrawlJob, job_id)
        if job is None:
            return None

        _ensure_transition(job.status, "running")

        if job.started_at is None:
            job.started_at = started_at or datetime.now(timezone.utc)
        job.finished_at = None
        job.status = "running"

        normalized_message = _as_str(message)
        if normalized_message is not None:
            job.message = normalized_message
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
    ) -> CrawlJob | None:
        if job_id is None:
            return None

        deltas = {
            "pages_fetched": _normalize_non_negative_delta(pages_fetched, field_name="pages_fetched"),
            "documents_saved": _normalize_non_negative_delta(documents_saved, field_name="documents_saved"),
            "notices_upserted": _normalize_non_negative_delta(notices_upserted, field_name="notices_upserted"),
            "deduplicated_count": _normalize_non_negative_delta(deduplicated_count, field_name="deduplicated_count"),
            "error_count": _normalize_non_negative_delta(error_count, field_name="error_count"),
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
        return job

    def finish_job_in_session(
        self,
        session: Session,
        *,
        job_id: int,
        status: str | None = None,
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
        if job.started_at is None:
            job.started_at = now
        job.finished_at = now
        job.status = target_status

        normalized_message = _as_str(message)
        if normalized_message is not None:
            job.message = normalized_message
        return job

    def _infer_success_status(self, job: CrawlJob) -> str:
        return "partial" if job.error_count > 0 else "succeeded"


def _ensure_source_site(
    session: Session,
    *,
    source_code: str,
    source_name: str | None,
    source_url: str | None,
) -> SourceSite:
    code = _as_str(source_code)
    if not code:
        raise ValueError("source_code is required")

    source = session.scalar(select(SourceSite).where(SourceSite.code == code))
    if source is not None:
        return source

    source = SourceSite(
        **_model_create_kwargs(
            session,
            SourceSite,
            code=code,
            name=_as_str(source_name) or code,
            base_url=_as_str(source_url) or "https://example.com",
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
        started_at=job.started_at,
        finished_at=job.finished_at,
        pages_fetched=int(job.pages_fetched or 0),
        documents_saved=int(job.documents_saved or 0),
        notices_upserted=int(job.notices_upserted or 0),
        deduplicated_count=int(job.deduplicated_count or 0),
        error_count=int(job.error_count or 0),
        message=job.message,
    )


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


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
