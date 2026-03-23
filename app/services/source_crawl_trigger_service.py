from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
# Bandit B404 false positive: crawl workers intentionally use subprocess with validated argv and shell=False.
import subprocess  # nosec B404
import sys
import time
from typing import Callable, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import build_log_extra
from app.models import CrawlError, CrawlJob, RawDocument, SourceSite
from app.services.crawl_job_payloads import (
    build_job_params_payload,
    build_runtime_stats_payload,
    read_payload_int,
)
from app.services.source_adapter_registry import get_source_adapter, resolve_spider_name, supports_job_type
from app.services.crawl_job_service import (
    ACTIVE_CRAWL_JOB_STATUSES,
    CrawlJobService,
    CrawlJobSnapshot,
    DEFAULT_RUNNING_LEASE_SECONDS,
    reconcile_expired_jobs_in_session,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_DISPATCH_RETRY_ATTEMPTS = 3
DEFAULT_DISPATCH_RETRY_DELAY_SECONDS = 1.0
_SOURCE_CODE_PATTERN = re.compile(r"^[a-z0-9_]+$")
_SPIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_SPIDER_ARG_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_DISPATCH_JOB_TYPES = frozenset({"manual", "scheduled", "backfill", "manual_retry"})
_ALLOWED_SPIDER_ARG_KEYS = frozenset({"job_type", "max_pages", "backfill_year"})


class CrawlCommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        heartbeat_callback: Callable[[], None] | None = None,
        heartbeat_interval_seconds: int = 30,
    ) -> int:
        """Run crawl command and return process exit code."""


class SubprocessCrawlCommandRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        heartbeat_callback: Callable[[], None] | None = None,
        heartbeat_interval_seconds: int = 30,
    ) -> int:
        _validate_scrapy_subprocess_command(command)
        # Bandit B603 reviewed: command prefix and argv fragments are validated; shell=False.
        process = subprocess.Popen(  # nosec B603
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        interval = max(int(heartbeat_interval_seconds), 1)
        while True:
            try:
                return int(process.wait(timeout=interval))
            except subprocess.TimeoutExpired:
                if heartbeat_callback is not None:
                    heartbeat_callback()


@dataclass(slots=True)
class CrawlJobDispatchRequest:
    source_code: str
    crawl_job_id: int
    job_type: str
    max_pages: int | None
    backfill_year: int | None
    triggered_by: str | None = None


class CrawlJobDispatcher(Protocol):
    def dispatch(
        self,
        request: CrawlJobDispatchRequest,
        *,
        project_root: Path,
        database_url: str,
        ) -> None:
        """Dispatch crawl job execution out of the request lifecycle."""


class NoOpCrawlJobDispatcher:
    def dispatch(
        self,
        request: CrawlJobDispatchRequest,
        *,
        project_root: Path,
        database_url: str,
    ) -> None:
        _ = (request, project_root, database_url)


class SubprocessCrawlJobDispatcher:
    def __init__(
        self,
        *,
        max_dispatch_attempts: int = DEFAULT_DISPATCH_RETRY_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_DISPATCH_RETRY_DELAY_SECONDS,
    ) -> None:
        self.max_dispatch_attempts = max(int(max_dispatch_attempts), 1)
        self.retry_delay_seconds = max(float(retry_delay_seconds), 0.0)

    def dispatch(
        self,
        request: CrawlJobDispatchRequest,
        *,
        project_root: Path,
        database_url: str,
    ) -> None:
        crawl_job_service = CrawlJobService.from_database_url(database_url)
        try:
            claimed_job = crawl_job_service.claim_pending_job(request.crawl_job_id)
            if claimed_job is None:
                return

            logs_dir = project_root / "logs" / "crawl_jobs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / f"crawl_job_{int(request.crawl_job_id)}.log"
            command = self._build_command(request=request, database_url=database_url)
            env = dict(os.environ)
            env.setdefault("PYTHONUNBUFFERED", "1")

            for attempt in range(1, self.max_dispatch_attempts + 1):
                try:
                    with log_path.open("ab") as log_file:
                        _validate_worker_subprocess_command(command)
                        # Bandit B603 reviewed: detached worker argv is validated before launch; shell=False.
                        subprocess.Popen(  # nosec B603
                            command,
                            cwd=project_root,
                            stdin=subprocess.DEVNULL,
                            stdout=log_file,
                            stderr=log_file,
                            env=env,
                            start_new_session=True,
                            close_fds=True,
                        )
                    LOGGER.info(
                        "crawl job dispatched",
                        extra=build_log_extra(
                            event="crawl_job_dispatched",
                            source_code=request.source_code,
                            crawl_job_id=request.crawl_job_id,
                            job_type=request.job_type,
                            triggered_by=request.triggered_by or claimed_job.triggered_by,
                            max_pages=request.max_pages,
                            backfill_year=request.backfill_year,
                            attempt=attempt,
                        ),
                    )
                    return
                except Exception as exc:
                    if attempt < self.max_dispatch_attempts:
                        LOGGER.warning(
                            "crawl job dispatch will retry",
                            extra=build_log_extra(
                                event="crawl_job_dispatch_retry",
                                source_code=request.source_code,
                                crawl_job_id=request.crawl_job_id,
                                job_type=request.job_type,
                                triggered_by=request.triggered_by or claimed_job.triggered_by,
                                max_pages=request.max_pages,
                                backfill_year=request.backfill_year,
                                attempt=attempt,
                                failure_reason=str(exc),
                            ),
                        )
                        if self.retry_delay_seconds > 0:
                            time.sleep(self.retry_delay_seconds)
                        continue

                    crawl_job_service.fail_job_if_active(
                        request.crawl_job_id,
                        job_params_json=build_job_params_payload(
                            source_code=request.source_code,
                            job_type=request.job_type,
                            triggered_by=request.triggered_by or claimed_job.triggered_by,
                            max_pages=request.max_pages,
                            backfill_year=request.backfill_year,
                            retry_of_job_id=claimed_job.retry_of_job_id,
                        ),
                        runtime_stats_json=_build_dispatch_failure_runtime_stats(),
                        failure_reason=f"后台任务派发失败：{exc}",
                        message=_build_dispatch_failure_message(
                            request=request,
                            failure_reason=f"后台任务派发失败：{exc}",
                        ),
                    )
                    LOGGER.error(
                        "crawl job dispatch abandoned",
                        extra=build_log_extra(
                            event="crawl_job_dispatch_abandoned",
                            source_code=request.source_code,
                            crawl_job_id=request.crawl_job_id,
                            job_type=request.job_type,
                            triggered_by=request.triggered_by or claimed_job.triggered_by,
                            max_pages=request.max_pages,
                            backfill_year=request.backfill_year,
                            attempt=attempt,
                            failure_reason=str(exc),
                        ),
                    )
                    return
        finally:
            crawl_job_service.close()

    def _build_command(self, *, request: CrawlJobDispatchRequest, database_url: str) -> list[str]:
        _validate_source_code_for_subprocess(request.source_code)
        _validate_job_type_for_subprocess(request.job_type)
        _validate_database_url_for_subprocess(database_url)
        if request.max_pages is not None and int(request.max_pages) < 1:
            raise ValueError("max_pages must be >= 1")
        if request.backfill_year is not None and int(request.backfill_year) < 2000:
            raise ValueError("backfill_year must be >= 2000")
        command = [
            _resolved_python_executable(),
            "-m",
            "app.run_crawl_job",
            "--database-url",
            database_url,
            "--source-code",
            request.source_code,
            "--crawl-job-id",
            str(int(request.crawl_job_id)),
            "--job-type",
            request.job_type,
        ]
        if request.max_pages is not None:
            command.extend(["--max-pages", str(int(request.max_pages))])
        if request.backfill_year is not None:
            command.extend(["--backfill-year", str(int(request.backfill_year))])
        return command


class SourceActiveCrawlJobConflictError(RuntimeError):
    def __init__(
        self,
        *,
        source_code: str,
        source_site_id: int,
        active_job_id: int | None,
        active_job_status: str | None,
    ) -> None:
        self.source_code = source_code
        self.source_site_id = source_site_id
        self.active_job_id = active_job_id
        self.active_job_status = active_job_status
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        if self.active_job_id is not None and self.active_job_status:
            return (
                f"来源 {self.source_code} 已有进行中的抓取任务 #{self.active_job_id}"
                f"（{self.active_job_status}），请等待当前任务结束后再试"
            )
        return f"来源 {self.source_code} 已有进行中的抓取任务，请等待当前任务结束后再试"


class CrawlJobRetryConflictError(RuntimeError):
    def __init__(
        self,
        *,
        original_job_id: int,
        retry_job_id: int | None = None,
    ) -> None:
        self.original_job_id = original_job_id
        self.retry_job_id = retry_job_id
        super().__init__("job already retried")


class CrawlJobRetryValidationError(RuntimeError):
    pass


class CrawlJobRetryNotFoundError(RuntimeError):
    pass


class CrawlJobStartConflictError(RuntimeError):
    def __init__(self, *, crawl_job_id: int, current_status: str) -> None:
        self.crawl_job_id = int(crawl_job_id)
        self.current_status = current_status
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        if self.current_status == "running":
            return f"crawl_job 已被其他 worker 原子领取并进入 running：{self.crawl_job_id}"
        return f"crawl_job 当前状态不允许再次启动：id={self.crawl_job_id}, status={self.current_status}"


@dataclass(slots=True)
class SourceCrawlTriggerResult:
    job: CrawlJobSnapshot
    command: list[str]
    return_code: int


@dataclass(slots=True)
class SourceCrawlEnqueueResult:
    job: CrawlJobSnapshot


class SourceCrawlTriggerService:
    """Create crawl jobs and trigger crawl execution."""

    def __init__(
        self,
        *,
        session: Session,
        command_runner: CrawlCommandRunner | None = None,
        job_dispatcher: CrawlJobDispatcher | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.session = session
        self.command_runner = command_runner or SubprocessCrawlCommandRunner()
        self.job_dispatcher = job_dispatcher or SubprocessCrawlJobDispatcher()
        self.project_root = project_root or Path(__file__).resolve().parents[2]

        bind = self.session.get_bind()
        if bind is None:
            raise RuntimeError("database bind is required")
        self.database_url = _database_url_for_bind(bind)
        self.crawl_job_service = CrawlJobService(
            session_factory=sessionmaker(bind=bind, autoflush=False, autocommit=False, expire_on_commit=False)
        )

    def trigger_manual_crawl(
        self,
        *,
        source: SourceSite,
        max_pages: int | None,
        triggered_by: str = "api",
    ) -> SourceCrawlTriggerResult:
        return self._trigger_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="manual",
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=None,
                job_type="manual",
            ),
        )

    def queue_manual_crawl(
        self,
        *,
        source: SourceSite,
        max_pages: int | None,
        triggered_by: str = "api",
    ) -> SourceCrawlEnqueueResult:
        return self._enqueue_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="manual",
            retry_of_job_id=None,
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=None,
                job_type="manual",
            ),
        )

    def create_manual_crawl_job(
        self,
        *,
        source: SourceSite,
        max_pages: int | None,
        triggered_by: str = "admin_ui",
        message: str = "manual crawl requested from admin ui",
    ) -> CrawlJobSnapshot:
        self._resolve_spider_name_for_source(source=source, job_type="manual")
        spider_args = self._build_spider_args(max_pages=max_pages, backfill_year=None, job_type="manual")
        return self._create_crawl_job(
            source=source,
            triggered_by=triggered_by,
            job_type="manual",
            job_params_json=self._build_job_params_json(
                source_code=source.code,
                job_type="manual",
                triggered_by=triggered_by,
                spider_args=spider_args,
                retry_of_job_id=None,
            ),
            runtime_stats_json=build_runtime_stats_payload(run_stage="queued"),
            failure_reason=None,
            message=message,
            retry_of_job_id=None,
        )

    def execute_manual_crawl_job(
        self,
        *,
        source: SourceSite,
        crawl_job_id: int,
        max_pages: int | None,
    ) -> SourceCrawlTriggerResult:
        return self.execute_crawl_job(
            source=source,
            crawl_job_id=crawl_job_id,
            job_type="manual",
            max_pages=max_pages,
            backfill_year=None,
        )

    def trigger_backfill_crawl(
        self,
        *,
        source: SourceSite,
        backfill_year: int,
        max_pages: int | None,
        triggered_by: str = "api-backfill",
    ) -> SourceCrawlTriggerResult:
        if backfill_year < 2000:
            raise ValueError("backfill_year must be >= 2000")
        return self._trigger_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="backfill",
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=backfill_year,
                job_type="backfill",
            ),
        )

    def queue_backfill_crawl(
        self,
        *,
        source: SourceSite,
        backfill_year: int,
        max_pages: int | None,
        triggered_by: str = "api-backfill",
    ) -> SourceCrawlEnqueueResult:
        if backfill_year < 2000:
            raise ValueError("backfill_year must be >= 2000")
        return self._enqueue_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="backfill",
            retry_of_job_id=None,
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=backfill_year,
                job_type="backfill",
            ),
        )

    def trigger_scheduled_crawl(
        self,
        *,
        source: SourceSite,
        max_pages: int | None,
        triggered_by: str = "scheduler",
    ) -> SourceCrawlTriggerResult:
        return self._trigger_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="scheduled",
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=None,
                job_type="scheduled",
            ),
        )

    def trigger_retry_crawl(
        self,
        *,
        source: SourceSite,
        retry_of_job_id: int,
        max_pages: int | None,
        backfill_year: int | None = None,
        triggered_by: str = "admin-retry",
    ) -> SourceCrawlTriggerResult:
        return self._trigger_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="manual_retry",
            retry_of_job_id=retry_of_job_id,
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=backfill_year,
                job_type="manual_retry",
            ),
        )

    def queue_retry_crawl(
        self,
        *,
        source: SourceSite,
        retry_of_job_id: int,
        max_pages: int | None,
        backfill_year: int | None = None,
        triggered_by: str = "admin-retry",
    ) -> SourceCrawlEnqueueResult:
        return self._enqueue_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="manual_retry",
            retry_of_job_id=retry_of_job_id,
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=backfill_year,
                job_type="manual_retry",
            ),
        )

    def queue_retry_crawl_for_job(
        self,
        *,
        crawl_job_id: int,
        max_pages: int | None,
        triggered_by: str = "admin-retry",
    ) -> SourceCrawlEnqueueResult:
        job = self.session.get(CrawlJob, int(crawl_job_id))
        if job is None:
            raise CrawlJobRetryNotFoundError("crawl_job not found")
        if str(job.status) not in {"failed", "partial"}:
            raise CrawlJobRetryValidationError("only failed or partial job can be retried")
        if job.retry_of_job_id is not None:
            raise CrawlJobRetryValidationError("retry job cannot be retried again")

        source = self.session.get(SourceSite, int(job.source_site_id))
        if source is None:
            raise CrawlJobRetryNotFoundError("source not found")

        existing_retry = self._load_retry_job_for_original_job(original_job_id=int(job.id))
        if existing_retry is not None:
            raise self._build_retry_conflict(
                original_job_id=int(job.id),
                existing_retry=existing_retry,
            )

        inherited_backfill_year = read_payload_int(job.job_params_json, "backfill_year")
        inherited_max_pages = read_payload_int(job.job_params_json, "max_pages")
        resolved_max_pages = (
            max_pages if max_pages is not None else inherited_max_pages or int(source.default_max_pages)
        )

        return self._enqueue_crawl(
            source=source,
            triggered_by=triggered_by,
            job_type="manual_retry",
            retry_of_job_id=int(job.id),
            spider_args=self._build_spider_args(
                max_pages=resolved_max_pages,
                backfill_year=inherited_backfill_year,
                job_type="manual_retry",
            ),
        )

    def execute_crawl_job(
        self,
        *,
        source: SourceSite,
        crawl_job_id: int,
        job_type: str,
        max_pages: int | None,
        backfill_year: int | None = None,
    ) -> SourceCrawlTriggerResult:
        return self._run_existing_crawl_job(
            source=source,
            crawl_job_id=crawl_job_id,
            job_type=job_type,
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=backfill_year,
                job_type=job_type,
            ),
        )

    def _trigger_crawl(
        self,
        *,
        source: SourceSite,
        triggered_by: str,
        job_type: str,
        retry_of_job_id: int | None = None,
        spider_args: dict[str, str] | None = None,
    ) -> SourceCrawlTriggerResult:
        normalized_spider_args = dict(spider_args or {})
        job = self._create_crawl_job(
            source=source,
            triggered_by=triggered_by,
            job_type=job_type,
            job_params_json=self._build_job_params_json(
                source_code=source.code,
                job_type=job_type,
                triggered_by=triggered_by,
                spider_args=normalized_spider_args,
                retry_of_job_id=retry_of_job_id,
            ),
            runtime_stats_json=build_runtime_stats_payload(run_stage="queued"),
            failure_reason=None,
            message=self._build_queued_job_message(job_type=job_type, spider_args=normalized_spider_args),
            retry_of_job_id=retry_of_job_id,
        )
        return self._run_existing_crawl_job(
            source=source,
            crawl_job_id=job.id,
            job_type=job_type,
            spider_args=normalized_spider_args,
        )

    def _enqueue_crawl(
        self,
        *,
        source: SourceSite,
        triggered_by: str,
        job_type: str,
        retry_of_job_id: int | None = None,
        spider_args: dict[str, str] | None = None,
    ) -> SourceCrawlEnqueueResult:
        normalized_spider_args = dict(spider_args or {})
        job = self._create_crawl_job(
            source=source,
            triggered_by=triggered_by,
            job_type=job_type,
            job_params_json=self._build_job_params_json(
                source_code=source.code,
                job_type=job_type,
                triggered_by=triggered_by,
                spider_args=normalized_spider_args,
                retry_of_job_id=retry_of_job_id,
            ),
            runtime_stats_json=build_runtime_stats_payload(run_stage="queued"),
            failure_reason=None,
            message=self._build_queued_job_message(job_type=job_type, spider_args=normalized_spider_args),
            retry_of_job_id=retry_of_job_id,
        )
        request = CrawlJobDispatchRequest(
            source_code=source.code,
            crawl_job_id=job.id,
            job_type=job_type,
            max_pages=_as_int_or_none(normalized_spider_args.get("max_pages")),
            backfill_year=_as_int_or_none(normalized_spider_args.get("backfill_year")),
            triggered_by=triggered_by,
        )
        LOGGER.info(
            "crawl job enqueued",
            extra=build_log_extra(
                event="crawl_job_enqueued",
                source_code=source.code,
                crawl_job_id=job.id,
                job_type=job_type,
                triggered_by=triggered_by,
                max_pages=request.max_pages,
                backfill_year=request.backfill_year,
                retry_of_job_id=retry_of_job_id,
            ),
        )
        try:
            self.job_dispatcher.dispatch(
                request,
                project_root=self.project_root,
                database_url=self.database_url,
            )
        except Exception:
            LOGGER.warning(
                "crawl job enqueue completed but dispatcher handoff failed",
                extra=build_log_extra(
                    event="crawl_job_dispatch_retry",
                    source_code=source.code,
                    crawl_job_id=job.id,
                    job_type=job_type,
                    triggered_by=triggered_by,
                    max_pages=request.max_pages,
                    backfill_year=request.backfill_year,
                    failure_reason="dispatcher handoff from web request failed",
                ),
                exc_info=True,
            )
        return SourceCrawlEnqueueResult(job=job)

    def _create_crawl_job(
        self,
        *,
        source: SourceSite,
        triggered_by: str,
        job_type: str,
        job_params_json: dict[str, object] | None,
        runtime_stats_json: dict[str, object] | None,
        failure_reason: str | None,
        message: str,
        retry_of_job_id: int | None,
    ) -> CrawlJobSnapshot:
        self._resolve_spider_name_for_source(source=source, job_type=job_type)
        reconcile_expired_jobs_in_session(self.session)
        self._raise_if_source_has_active_job(source=source)
        try:
            job = self.crawl_job_service.create_job_in_session(
                self.session,
                source_code=source.code,
                source_name=source.name,
                source_url=source.base_url,
                job_type=job_type,
                triggered_by=triggered_by,
                retry_of_job_id=retry_of_job_id,
                job_params_json=job_params_json,
                runtime_stats_json=runtime_stats_json,
                failure_reason=failure_reason,
                message=message,
            )
            job_id = int(job.id)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            retry_conflict = self._resolve_retry_conflict_after_integrity_error(
                retry_of_job_id=retry_of_job_id,
                error=exc,
            )
            if retry_conflict is not None:
                raise retry_conflict from exc
            if self._is_source_active_job_integrity_error(exc):
                raise self._build_source_active_job_conflict(source=source) from exc
            raise
        snapshot = self.crawl_job_service.get_job(job_id)
        if snapshot is None:
            raise RuntimeError(f"crawl_job not found after creation: {job_id}")
        return snapshot

    def _run_existing_crawl_job(
        self,
        *,
        source: SourceSite,
        crawl_job_id: int,
        job_type: str,
        spider_args: dict[str, str] | None,
    ) -> SourceCrawlTriggerResult:
        normalized_spider_args = dict(spider_args or {})
        spider_name = self._resolve_spider_name_for_source(source=source, job_type=job_type)

        job = self.session.get(CrawlJob, int(crawl_job_id))
        if job is None:
            raise RuntimeError(f"crawl_job not found: {crawl_job_id}")
        if int(job.source_site_id) != int(source.id):
            raise ValueError(
                f"crawl_job source mismatch: crawl_job_id={crawl_job_id}, "
                f"source_site_id={job.source_site_id}, expected={source.id}"
            )
        if str(job.job_type) != job_type:
            raise ValueError(
                f"crawl_job job_type mismatch: crawl_job_id={crawl_job_id}, "
                f"job_type={job.job_type}, expected={job_type}"
            )

        started_job = self.crawl_job_service.start_job_in_session(
            self.session,
            job_id=int(crawl_job_id),
            job_params_json=self._build_job_params_json(
                source_code=source.code,
                job_type=job_type,
                triggered_by=job.triggered_by,
                spider_args=normalized_spider_args,
                retry_of_job_id=_as_job_retry_of_job_id(job),
                spider_name=spider_name,
            ),
            runtime_stats_json=build_runtime_stats_payload(
                run_stage="running",
                spider_name=spider_name,
            ),
            failure_reason=None,
            message=self._build_running_job_message(
                job_type=job_type,
                spider_name=spider_name,
                spider_args=normalized_spider_args,
            ),
            lease_seconds=DEFAULT_RUNNING_LEASE_SECONDS,
        )
        if started_job is None:
            self.session.rollback()
            current_job = self.session.get(CrawlJob, int(crawl_job_id))
            if current_job is None:
                raise RuntimeError(f"crawl_job not found: {crawl_job_id}")
            raise CrawlJobStartConflictError(
                crawl_job_id=int(crawl_job_id),
                current_status=str(current_job.status),
            )
        self.session.commit()
        job = started_job

        command = self._build_command(
            spider=spider_name,
            crawl_job_id=int(crawl_job_id),
            spider_args=normalized_spider_args,
        )

        def _heartbeat_callback() -> None:
            try:
                self.crawl_job_service.heartbeat_job(
                    int(crawl_job_id),
                    lease_seconds=DEFAULT_RUNNING_LEASE_SECONDS,
                )
            except Exception:
                LOGGER.warning(
                    "crawl job heartbeat update failed: crawl_job_id=%s",
                    crawl_job_id,
                    exc_info=True,
                )

        try:
            return_code = self.command_runner.run(
                command,
                cwd=self.project_root / "crawler",
                heartbeat_callback=_heartbeat_callback,
            )
        except Exception as exc:
            failed_snapshot = self.crawl_job_service.finish_job(
                int(crawl_job_id),
                status="failed",
                job_params_json=self._build_job_params_json(
                    source_code=source.code,
                    job_type=job_type,
                    triggered_by=job.triggered_by,
                    spider_args=normalized_spider_args,
                    retry_of_job_id=_as_job_retry_of_job_id(job),
                    spider_name=spider_name,
                ),
                runtime_stats_json=build_runtime_stats_payload(
                    run_stage="runner_error",
                    spider_name=spider_name,
                ),
                failure_reason=f"命令执行失败：{exc}",
                message=self._build_failure_message(
                    job_type=job_type,
                    run_stage="runner_error",
                    failure_reason=f"命令执行失败：{exc}",
                ),
            )
            if failed_snapshot is None:
                raise RuntimeError(f"crawl_job not found when command runner failed: {crawl_job_id}") from exc
            raise

        pages_scraped, first_publish_date_seen, last_publish_date_seen = self._collect_list_page_stats(int(crawl_job_id))
        snapshot = self.crawl_job_service.get_job(int(crawl_job_id))
        if snapshot is None:
            raise RuntimeError(f"crawl_job not found after spider finished: {crawl_job_id}")
        pages_metric = pages_scraped if pages_scraped > 0 else int(snapshot.pages_fetched or 0)
        failure_reason = self._infer_failure_reason(
            crawl_job_id=int(crawl_job_id),
            snapshot=snapshot,
            pages_scraped=pages_metric,
            return_code=return_code,
        )
        final_status = self._infer_final_status(
            snapshot=snapshot,
            failure_reason=failure_reason,
            return_code=return_code,
        )
        finalized = self.crawl_job_service.finish_job(
            int(crawl_job_id),
            status=final_status,
            job_params_json=self._build_job_params_json(
                source_code=source.code,
                job_type=job_type,
                triggered_by=job.triggered_by,
                spider_args=normalized_spider_args,
                retry_of_job_id=_as_job_retry_of_job_id(job),
                spider_name=spider_name,
            ),
            runtime_stats_json=self._build_final_runtime_stats_json(
                snapshot=snapshot,
                pages_scraped=pages_scraped,
                first_publish_date_seen=first_publish_date_seen,
                last_publish_date_seen=last_publish_date_seen,
                return_code=return_code,
            ),
            failure_reason=None if failure_reason == "-" else failure_reason,
            message=self._build_job_summary_message(
                final_status=final_status,
                job_type=job_type,
                snapshot=snapshot,
                pages_scraped=pages_scraped,
                first_publish_date_seen=first_publish_date_seen,
                last_publish_date_seen=last_publish_date_seen,
                return_code=return_code,
                failure_reason=failure_reason,
            ),
        )
        if finalized is None:
            raise RuntimeError(f"crawl_job not found when finalizing: {crawl_job_id}")
        snapshot = finalized

        return SourceCrawlTriggerResult(
            job=snapshot,
            command=command,
            return_code=return_code,
        )

    def _resolve_spider_name_for_source(self, *, source: SourceSite, job_type: str) -> str:
        adapter = get_source_adapter(source.code)
        if adapter is None:
            raise ValueError("仅保存来源信息，尚未接入抓取逻辑")
        if job_type != "scheduled" and not supports_job_type(source.code, job_type=job_type):
            supported_modes = " / ".join(adapter.supported_job_types)
            raise ValueError(f"source={source.code} 不支持 job_type={job_type}，支持模式: {supported_modes}")
        spider_name = resolve_spider_name(source.code)
        if not spider_name:
            raise ValueError(f"source={source.code} 未配置 spider")
        return spider_name

    def _build_command(self, *, spider: str, crawl_job_id: int, spider_args: dict[str, str]) -> list[str]:
        _validate_spider_name_for_subprocess(spider)
        _validate_database_url_for_subprocess(self.database_url)
        _validate_spider_args_for_subprocess(spider_args)
        command = [
            _resolved_python_executable(),
            "-m",
            "scrapy",
            "crawl",
            spider,
            "-a",
            f"crawl_job_id={crawl_job_id}",
            "-s",
            "CRAWLER_WRITER_BACKEND=sqlalchemy",
            "-s",
            f"CRAWLER_DATABASE_URL={self.database_url}",
        ]
        for key, value in spider_args.items():
            command.extend(["-a", f"{key}={value}"])
        return command

    def _build_spider_args(
        self,
        *,
        max_pages: int | None,
        backfill_year: int | None,
        job_type: str,
    ) -> dict[str, str]:
        args: dict[str, str] = {}
        if max_pages is not None:
            if max_pages < 1:
                raise ValueError("max_pages must be >= 1")
            args["max_pages"] = str(max_pages)
        if backfill_year is not None:
            if backfill_year < 2000:
                raise ValueError("backfill_year must be >= 2000")
            args["backfill_year"] = str(backfill_year)
        args["job_type"] = job_type
        return args

    def _collect_list_page_stats(self, crawl_job_id: int) -> tuple[int, str | None, str | None]:
        pages_scraped = 0
        first_publish_date_seen: str | None = None
        last_publish_date_seen: str | None = None
        try:
            metas = self.session.scalars(
                select(RawDocument.extra_meta).where(RawDocument.crawl_job_id == crawl_job_id)
            ).all()
            for meta in metas:
                if not isinstance(meta, dict):
                    continue
                if str(meta.get("role") or "").lower() != "list":
                    continue
                pages_scraped += 1
                candidates = [
                    self._normalize_iso_date(meta.get("list_page_publish_date_max")),
                    self._normalize_iso_date(meta.get("list_page_publish_date_min")),
                    self._normalize_iso_date(meta.get("first_publish_date_seen_total")),
                    self._normalize_iso_date(meta.get("last_publish_date_seen_total")),
                ]
                for value in candidates:
                    if value is None:
                        continue
                    if first_publish_date_seen is None or value > first_publish_date_seen:
                        first_publish_date_seen = value
                    if last_publish_date_seen is None or value < last_publish_date_seen:
                        last_publish_date_seen = value
        except Exception:
            return 0, None, None
        return pages_scraped, first_publish_date_seen, last_publish_date_seen

    def _normalize_iso_date(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
        return None

    def _build_final_runtime_stats_json(
        self,
        *,
        snapshot: CrawlJobSnapshot,
        pages_scraped: int,
        first_publish_date_seen: str | None,
        last_publish_date_seen: str | None,
        return_code: int,
    ) -> dict[str, object]:
        dedup_skipped = int(snapshot.list_items_source_duplicates_skipped or 0) + int(
            snapshot.source_duplicates_suppressed or 0
        )
        list_seen = int(snapshot.list_items_seen or 0)
        list_unique = int(snapshot.list_items_unique or 0)
        pages_metric = pages_scraped if pages_scraped > 0 else int(snapshot.pages_fetched or 0)
        return build_runtime_stats_payload(
            run_stage="finished",
            pages_scraped=pages_metric,
            list_seen=list_seen,
            list_unique=list_unique,
            detail_requests=int(snapshot.detail_pages_fetched or 0),
            dedup_skipped=dedup_skipped,
            notices_written=int(snapshot.notices_upserted or 0),
            raw_documents_written=int(snapshot.documents_saved or 0),
            first_publish_date_seen=first_publish_date_seen,
            last_publish_date_seen=last_publish_date_seen,
            return_code=return_code,
        )

    def _build_job_summary_message(
        self,
        *,
        final_status: str,
        job_type: str,
        snapshot: CrawlJobSnapshot,
        pages_scraped: int,
        first_publish_date_seen: str | None,
        last_publish_date_seen: str | None,
        return_code: int,
        failure_reason: str | None = None,
    ) -> str:
        runtime_stats = self._build_final_runtime_stats_json(
            snapshot=snapshot,
            pages_scraped=pages_scraped,
            first_publish_date_seen=first_publish_date_seen,
            last_publish_date_seen=last_publish_date_seen,
            return_code=return_code,
        )
        parts = [
            f"{job_type} 任务已结束",
            f"状态 {final_status}",
            f"列表页 {read_payload_int(runtime_stats, 'pages_scraped') or 0}",
            f"列表项 {read_payload_int(runtime_stats, 'list_unique') or 0}/{read_payload_int(runtime_stats, 'list_seen') or 0}",
            f"详情请求 {read_payload_int(runtime_stats, 'detail_requests') or 0}",
            f"公告 {read_payload_int(runtime_stats, 'notices_written') or 0}",
            f"归档 {read_payload_int(runtime_stats, 'raw_documents_written') or 0}",
            f"去重跳过 {read_payload_int(runtime_stats, 'dedup_skipped') or 0}",
        ]
        if first_publish_date_seen:
            parts.append(f"最早发布日期 {first_publish_date_seen}")
        if last_publish_date_seen:
            parts.append(f"最晚发布日期 {last_publish_date_seen}")
        normalized_failure_reason = (failure_reason or "").strip()
        if normalized_failure_reason and normalized_failure_reason != "-":
            parts.append(f"异常 {normalized_failure_reason}")
        if return_code != 0:
            parts.append(f"退出码 {return_code}")
        return "，".join(parts)

    def _build_queued_job_message(
        self,
        *,
        job_type: str,
        spider_args: dict[str, str],
    ) -> str:
        max_pages = _as_int_or_none(spider_args.get("max_pages"))
        backfill_year = _as_int_or_none(spider_args.get("backfill_year"))
        parts = [f"{job_type} 任务已入队，等待后台调度执行"]
        if max_pages is not None:
            parts.append(f"最大页数 {max_pages}")
        if backfill_year is not None:
            parts.append(f"回填年份 {backfill_year}")
        return "，".join(parts)

    def _build_running_job_message(
        self,
        *,
        job_type: str,
        spider_name: str,
        spider_args: dict[str, str],
    ) -> str:
        max_pages = _as_int_or_none(spider_args.get("max_pages"))
        backfill_year = _as_int_or_none(spider_args.get("backfill_year"))
        parts = [f"{job_type} 任务执行中（spider={spider_name}）"]
        if max_pages is not None:
            parts.append(f"最大页数 {max_pages}")
        if backfill_year is not None:
            parts.append(f"回填年份 {backfill_year}")
        return "，".join(parts)

    def _build_failure_message(
        self,
        *,
        job_type: str,
        run_stage: str,
        failure_reason: str,
    ) -> str:
        return f"{job_type} 任务在 {run_stage} 阶段失败：{failure_reason}"

    def _build_job_params_json(
        self,
        *,
        source_code: str,
        job_type: str,
        triggered_by: str | None,
        spider_args: dict[str, str],
        retry_of_job_id: int | None,
        spider_name: str | None = None,
    ) -> dict[str, object]:
        return build_job_params_payload(
            source_code=source_code,
            job_type=job_type,
            triggered_by=triggered_by,
            max_pages=_as_int_or_none(spider_args.get("max_pages")),
            backfill_year=_as_int_or_none(spider_args.get("backfill_year")),
            retry_of_job_id=retry_of_job_id,
            spider_name=spider_name,
        )

    def _infer_failure_reason(
        self,
        *,
        crawl_job_id: int,
        snapshot: CrawlJobSnapshot,
        pages_scraped: int,
        return_code: int,
    ) -> str:
        if return_code != 0:
            return f"页面获取失败: spider 进程退出({return_code})"

        errors = self.session.execute(
            select(CrawlError.stage, CrawlError.error_message).where(CrawlError.crawl_job_id == crawl_job_id)
        ).all()
        error_messages = [str(message).strip() for _, message in errors if message is not None and str(message).strip()]
        fetch_errors = [msg for stage, msg in errors if str(stage or "").lower() == "fetch" and msg]
        parse_errors = [msg for stage, msg in errors if str(stage or "").lower() == "parse" and msg]
        detail_parse_errors = [msg for msg in parse_errors if "详情" in str(msg) or "detail" in str(msg).lower()]

        if fetch_errors and pages_scraped <= 0:
            return self._prefix_failure_reason("页面获取失败", fetch_errors[0])
        if fetch_errors and int(snapshot.list_items_seen or 0) <= 0:
            return self._prefix_failure_reason("页面获取失败", fetch_errors[0])
        if int(snapshot.list_items_seen or 0) <= 0:
            return "列表解析为0"
        if detail_parse_errors:
            return self._prefix_failure_reason("详情解析失败", detail_parse_errors[0])
        if int(snapshot.detail_pages_fetched or 0) <= 0 and parse_errors:
            return self._prefix_failure_reason("详情解析失败", parse_errors[0])
        if error_messages:
            return self._prefix_failure_reason("详情解析失败", error_messages[0])
        return "-"

    def _infer_final_status(
        self,
        *,
        snapshot: CrawlJobSnapshot,
        failure_reason: str,
        return_code: int,
    ) -> str:
        if return_code != 0:
            return "failed"
        normalized_failure_reason = (failure_reason or "").strip()
        if normalized_failure_reason.startswith("页面获取失败"):
            return "failed"
        if int(snapshot.error_count or 0) > 0:
            return "partial"
        return "succeeded"

    def _prefix_failure_reason(self, prefix: str, reason: object) -> str:
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            return prefix
        if normalized_reason == prefix or normalized_reason.startswith(f"{prefix}:"):
            return normalized_reason
        return f"{prefix}: {normalized_reason}"

    def _raise_if_source_has_active_job(self, *, source: SourceSite) -> None:
        active_job = self._load_active_job_for_source(source_id=int(source.id))
        if active_job is None:
            return
        raise self._build_source_active_job_conflict(source=source, active_job=active_job)

    def _build_source_active_job_conflict(
        self,
        *,
        source: SourceSite,
        active_job: CrawlJob | None = None,
    ) -> SourceActiveCrawlJobConflictError:
        resolved_active_job = active_job or self._load_active_job_for_source(source_id=int(source.id))
        return SourceActiveCrawlJobConflictError(
            source_code=source.code,
            source_site_id=int(source.id),
            active_job_id=int(resolved_active_job.id) if resolved_active_job is not None else None,
            active_job_status=str(resolved_active_job.status) if resolved_active_job is not None else None,
        )

    def _load_active_job_for_source(self, *, source_id: int) -> CrawlJob | None:
        return self.session.scalar(
            select(CrawlJob)
            .where(
                CrawlJob.source_site_id == int(source_id),
                CrawlJob.status.in_(sorted(ACTIVE_CRAWL_JOB_STATUSES)),
            )
            .order_by(CrawlJob.id.desc())
            .limit(1)
        )

    def _load_retry_job_for_original_job(self, *, original_job_id: int) -> CrawlJob | None:
        return self.session.scalar(
            select(CrawlJob)
            .where(CrawlJob.retry_of_job_id == int(original_job_id))
            .order_by(CrawlJob.id.desc())
            .limit(1)
        )

    def _build_retry_conflict(
        self,
        *,
        original_job_id: int,
        existing_retry: CrawlJob | None = None,
    ) -> CrawlJobRetryConflictError:
        return CrawlJobRetryConflictError(
            original_job_id=int(original_job_id),
            retry_job_id=int(existing_retry.id) if existing_retry is not None else None,
        )

    def _resolve_retry_conflict_after_integrity_error(
        self,
        *,
        retry_of_job_id: int | None,
        error: IntegrityError,
    ) -> CrawlJobRetryConflictError | None:
        if retry_of_job_id is None:
            return None

        existing_retry = self._load_retry_job_for_original_job(original_job_id=int(retry_of_job_id))
        if existing_retry is not None:
            return self._build_retry_conflict(
                original_job_id=int(retry_of_job_id),
                existing_retry=existing_retry,
            )
        if self._is_retry_of_job_integrity_error(error):
            return self._build_retry_conflict(original_job_id=int(retry_of_job_id))
        return None

    def _is_source_active_job_integrity_error(self, error: IntegrityError) -> bool:
        raw_message = str(getattr(error, "orig", error)).lower()
        return "uq_crawl_job_source_active" in raw_message or (
            "unique constraint failed" in raw_message and "crawl_job.source_site_id" in raw_message
        )

    def _is_retry_of_job_integrity_error(self, error: IntegrityError) -> bool:
        raw_message = str(getattr(error, "orig", error)).lower()
        return "uq_crawl_job_retry_of_job_id" in raw_message or (
            "unique constraint failed" in raw_message and "crawl_job.retry_of_job_id" in raw_message
        )


def _database_url_for_bind(bind: object) -> str:
    url = getattr(bind, "url", None)
    if url is None:
        raise RuntimeError("database bind url is required")
    render_as_string = getattr(url, "render_as_string", None)
    if callable(render_as_string):
        return str(render_as_string(hide_password=False))
    return str(url)


def _resolved_python_executable() -> str:
    return str(Path(sys.executable).resolve())


def _validate_subprocess_fragment(value: object, *, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if any(char in text for char in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains unsupported control characters")
    return text


def _validate_database_url_for_subprocess(database_url: str) -> str:
    return _validate_subprocess_fragment(database_url, label="database_url")


def _validate_source_code_for_subprocess(source_code: str) -> str:
    normalized = _validate_subprocess_fragment(source_code, label="source_code")
    if not _SOURCE_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("source_code contains unsupported characters")
    return normalized


def _validate_job_type_for_subprocess(job_type: str) -> str:
    normalized = _validate_subprocess_fragment(job_type, label="job_type")
    if normalized not in _ALLOWED_DISPATCH_JOB_TYPES:
        raise ValueError(f"unsupported job_type for subprocess dispatch: {normalized}")
    return normalized


def _validate_spider_name_for_subprocess(spider: str) -> str:
    normalized = _validate_subprocess_fragment(spider, label="spider")
    if not _SPIDER_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("spider contains unsupported characters")
    return normalized


def _validate_spider_args_for_subprocess(spider_args: dict[str, str]) -> None:
    for key, value in spider_args.items():
        normalized_key = _validate_subprocess_fragment(key, label="spider arg key")
        if not _SPIDER_ARG_KEY_PATTERN.fullmatch(normalized_key):
            raise ValueError(f"unsupported spider arg key: {normalized_key}")
        if normalized_key not in _ALLOWED_SPIDER_ARG_KEYS:
            raise ValueError(f"spider arg is not allowed for subprocess dispatch: {normalized_key}")
        _validate_subprocess_fragment(value, label=f"spider arg value[{normalized_key}]")


def _validate_scrapy_subprocess_command(command: list[str]) -> None:
    if len(command) < 6:
        raise ValueError("scrapy command is incomplete")
    executable = Path(_validate_subprocess_fragment(command[0], label="python executable"))
    if not executable.is_absolute():
        raise ValueError("python executable must be absolute")
    if command[1:4] != ["-m", "scrapy", "crawl"]:
        raise ValueError("unexpected scrapy command prefix")
    for argument in command[1:]:
        _validate_subprocess_fragment(argument, label="scrapy argv")


def _validate_worker_subprocess_command(command: list[str]) -> None:
    if len(command) < 8:
        raise ValueError("worker command is incomplete")
    executable = Path(_validate_subprocess_fragment(command[0], label="python executable"))
    if not executable.is_absolute():
        raise ValueError("python executable must be absolute")
    if command[1:3] != ["-m", "app.run_crawl_job"]:
        raise ValueError("unexpected worker command prefix")
    for argument in command[3:]:
        _validate_subprocess_fragment(argument, label="worker argv")


def _as_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_job_retry_of_job_id(job: CrawlJob) -> int | None:
    if job.retry_of_job_id is None:
        return None
    return int(job.retry_of_job_id)


def _build_dispatch_failure_message(
    *,
    request: CrawlJobDispatchRequest,
    failure_reason: str,
) -> str:
    return f"{request.job_type} 任务派发失败：{failure_reason}"


def _build_dispatch_failure_runtime_stats() -> dict[str, object]:
    return build_runtime_stats_payload(run_stage="dispatch_abandoned")
