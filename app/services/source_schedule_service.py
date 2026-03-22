from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import SourceSite
from app.services.source_crawl_trigger_service import (
    CrawlCommandRunner,
    SourceActiveCrawlJobConflictError,
    SourceCrawlTriggerService,
)

SCHEDULE_DAY_OPTIONS = {1, 2, 3, 7}
SCHEDULE_STATUS_OPTIONS = {"succeeded", "failed", "partial", "skipped"}
SOURCE_SCHEDULE_JOB_PREFIX = "source_schedule::"
SOURCE_SCHEDULE_REFRESH_JOB_ID = "source_schedule_runtime::refresh"


@dataclass(slots=True)
class SourceScheduleSnapshot:
    source_code: str
    schedule_enabled: bool
    schedule_days: int
    next_scheduled_run_at: datetime | None
    last_scheduled_run_at: datetime | None
    last_schedule_status: str | None


class SourceScheduleRuntime:
    """Scheduler runtime for source auto-crawl backed by in-memory APScheduler jobs."""

    def __init__(
        self,
        *,
        database_url: str,
        command_runner: CrawlCommandRunner | None = None,
        refresh_interval_seconds: int = 30,
    ) -> None:
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(bind=self._engine, autoflush=False, autocommit=False, expire_on_commit=False)
        self.command_runner = command_runner
        self.refresh_interval_seconds = max(int(refresh_interval_seconds), 1)
        self.scheduler = BackgroundScheduler(timezone=timezone.utc)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.scheduler.start()
        try:
            self.restore_from_db()
            self._register_refresh_job()
        except Exception:
            self.scheduler.shutdown(wait=False)
            self._started = False
            raise
        self._started = True

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self._started = False
        self._engine.dispose()

    def restore_from_db(self) -> None:
        with self.session_factory() as session:
            sources = session.scalars(select(SourceSite)).all()
            active_source_codes: set[str] = set()
            for source in sources:
                active_source_codes.add(source.code)
                self._sync_source_in_session(session, source)
            self._remove_stale_source_jobs(active_source_codes)
            session.commit()

    def sync_source(self, source_code: str) -> None:
        with self.session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
            if source is None:
                self._remove_job_if_exists(self._job_id(source_code))
                return
            self._sync_source_in_session(session, source)
            session.commit()

    def _sync_source_in_session(self, session: Session, source: SourceSite) -> None:
        job_id = self._job_id(source.code)
        if not self._should_schedule(source):
            self._remove_job_if_exists(job_id)
            source.next_scheduled_run_at = None
            session.add(source)
            return

        days = int(source.schedule_days)
        existing_job = self.scheduler.get_job(job_id)
        if existing_job is not None and self._job_matches_source(existing_job, source):
            source.next_scheduled_run_at = existing_job.next_run_time
            session.add(source)
            return

        next_run = self._resolve_next_run_time(source, days=days)
        self.scheduler.add_job(
            self._run_scheduled_source,
            trigger=IntervalTrigger(days=days, timezone=timezone.utc),
            id=job_id,
            kwargs={"source_code": source.code},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=next_run,
            misfire_grace_time=3600,
        )
        job = self.scheduler.get_job(job_id)
        source.next_scheduled_run_at = job.next_run_time if job is not None else next_run
        session.add(source)

    def _run_scheduled_source(self, source_code: str) -> None:
        with self.session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
            if source is None:
                self._remove_job_if_exists(self._job_id(source_code))
                return

            if not self._should_schedule(source):
                self._remove_job_if_exists(self._job_id(source_code))
                source.next_scheduled_run_at = None
                session.add(source)
                session.commit()
                return

            source.last_scheduled_run_at = datetime.now(timezone.utc)
            session.add(source)
            session.commit()

            trigger_service = SourceCrawlTriggerService(session=session, command_runner=self.command_runner)
            status = "failed"
            try:
                result = trigger_service.trigger_scheduled_crawl(
                    source=source,
                    max_pages=source.default_max_pages,
                    triggered_by="scheduler",
                )
                status = result.job.status
            except SourceActiveCrawlJobConflictError:
                session.rollback()
                status = "skipped"
                source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
                if source is None:
                    return
            except Exception:
                session.rollback()
                source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
                if source is None:
                    return

            if status not in SCHEDULE_STATUS_OPTIONS:
                status = "failed"

            job = self.scheduler.get_job(self._job_id(source_code))
            source.last_schedule_status = status
            source.next_scheduled_run_at = job.next_run_time if job is not None else None
            session.add(source)
            session.commit()

    def _remove_job_if_exists(self, job_id: str) -> None:
        try:
            self.scheduler.remove_job(job_id)
        except JobLookupError:
            return

    def _register_refresh_job(self) -> None:
        next_run = datetime.now(timezone.utc) + timedelta(seconds=self.refresh_interval_seconds)
        self.scheduler.add_job(
            self.restore_from_db,
            trigger=IntervalTrigger(seconds=self.refresh_interval_seconds, timezone=timezone.utc),
            id=SOURCE_SCHEDULE_REFRESH_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=next_run,
            misfire_grace_time=max(self.refresh_interval_seconds, 1),
        )

    def _remove_stale_source_jobs(self, active_source_codes: set[str]) -> None:
        active_job_ids = {self._job_id(source_code) for source_code in active_source_codes}
        for job in self.scheduler.get_jobs():
            if job.id == SOURCE_SCHEDULE_REFRESH_JOB_ID:
                continue
            if not job.id.startswith(SOURCE_SCHEDULE_JOB_PREFIX):
                continue
            if job.id in active_job_ids:
                continue
            self._remove_job_if_exists(job.id)

    @staticmethod
    def _job_matches_source(job, source: SourceSite) -> bool:
        trigger = getattr(job, "trigger", None)
        if not isinstance(trigger, IntervalTrigger):
            return False
        return trigger.interval == timedelta(days=int(source.schedule_days))

    @staticmethod
    def _resolve_next_run_time(source: SourceSite, *, days: int) -> datetime:
        next_run = source.next_scheduled_run_at
        now = datetime.now(timezone.utc)
        if next_run is None:
            return now + timedelta(days=days)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        if next_run <= now:
            return now
        return next_run

    @staticmethod
    def _should_schedule(source: SourceSite) -> bool:
        return bool(
            source.is_active
            and source.schedule_enabled
            and int(source.schedule_days) in SCHEDULE_DAY_OPTIONS
        )

    @staticmethod
    def _job_id(source_code: str) -> str:
        return f"{SOURCE_SCHEDULE_JOB_PREFIX}{source_code}"


def calculate_next_scheduled_run(
    *,
    schedule_enabled: bool,
    schedule_days: int,
    is_active: bool,
) -> datetime | None:
    if not schedule_enabled or not is_active or schedule_days not in SCHEDULE_DAY_OPTIONS:
        return None
    return datetime.now(timezone.utc) + timedelta(days=int(schedule_days))


_global_source_schedule_runtime: SourceScheduleRuntime | None = None


def initialize_source_schedule_runtime(
    database_url: str,
    *,
    refresh_interval_seconds: int = 30,
) -> SourceScheduleRuntime:
    global _global_source_schedule_runtime
    if _global_source_schedule_runtime is None:
        _global_source_schedule_runtime = SourceScheduleRuntime(
            database_url=database_url,
            refresh_interval_seconds=refresh_interval_seconds,
        )
    return _global_source_schedule_runtime


def get_source_schedule_runtime() -> SourceScheduleRuntime | None:
    return _global_source_schedule_runtime


def shutdown_source_schedule_runtime() -> None:
    global _global_source_schedule_runtime
    if _global_source_schedule_runtime is None:
        return
    _global_source_schedule_runtime.shutdown()
    _global_source_schedule_runtime = None


def sync_source_schedule(
    source_code: str,
    *,
    fallback_session: Session | None = None,
) -> None:
    if fallback_session is not None:
        source = fallback_session.scalar(select(SourceSite).where(SourceSite.code == source_code))
        if source is not None:
            source.next_scheduled_run_at = calculate_next_scheduled_run(
                schedule_enabled=bool(source.schedule_enabled),
                schedule_days=int(source.schedule_days),
                is_active=bool(source.is_active),
            )
            fallback_session.add(source)
            fallback_session.commit()
            fallback_session.refresh(source)

    runtime = get_source_schedule_runtime()
    if runtime is None:
        return

    try:
        runtime.sync_source(source_code)
    except Exception:
        return
