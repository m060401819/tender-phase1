from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path

from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import build_log_extra
from app.models import CrawlJob, SourceSite
from app.services.crawl_job_payloads import read_payload_int
from app.services.source_crawl_trigger_service import (
    CrawlJobDispatchRequest,
    CrawlJobDispatcher,
    SubprocessCrawlJobDispatcher,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_PENDING_DISPATCH_LIMIT = 20


@dataclass(slots=True)
class PendingCrawlJobDispatchSweepResult:
    scanned_count: int = 0
    handoff_count: int = 0
    abandoned_count: int = 0


class PendingCrawlJobDispatchService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        database_url: str,
        job_dispatcher: CrawlJobDispatcher | None = None,
        project_root: Path | None = None,
        engine=None,
    ) -> None:
        self.session_factory = session_factory
        self.database_url = database_url
        self.job_dispatcher = job_dispatcher or SubprocessCrawlJobDispatcher()
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._owned_engine = engine

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        *,
        job_dispatcher: CrawlJobDispatcher | None = None,
        project_root: Path | None = None,
    ) -> "PendingCrawlJobDispatchService":
        engine = create_engine(database_url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        return cls(
            session_factory=session_factory,
            database_url=database_url,
            job_dispatcher=job_dispatcher,
            project_root=project_root,
            engine=engine,
        )

    def close(self) -> None:
        if self._owned_engine is not None:
            self._owned_engine.dispose()
            self._owned_engine = None

    def dispatch_pending_jobs(
        self,
        *,
        limit: int = DEFAULT_PENDING_DISPATCH_LIMIT,
    ) -> PendingCrawlJobDispatchSweepResult:
        result = PendingCrawlJobDispatchSweepResult()
        with self.session_factory() as session:
            candidates = self._load_candidates(session, limit=max(int(limit), 1))

        for candidate in candidates:
            result.scanned_count += 1
            try:
                self.job_dispatcher.dispatch(
                    candidate,
                    project_root=self.project_root,
                    database_url=self.database_url,
                )
            except Exception as exc:
                result.abandoned_count += 1
                LOGGER.exception(
                    "pending crawl job dispatch handoff failed",
                    extra=build_log_extra(
                        event="crawl_job_dispatch_abandoned",
                        source_code=candidate.source_code,
                        crawl_job_id=candidate.crawl_job_id,
                        job_type=candidate.job_type,
                        triggered_by=candidate.triggered_by,
                        max_pages=candidate.max_pages,
                        backfill_year=candidate.backfill_year,
                        failure_reason=f"dispatcher sweep handoff failed: {exc}",
                    ),
                )
                continue
            result.handoff_count += 1
        return result

    def _load_candidates(self, session: Session, *, limit: int) -> list[CrawlJobDispatchRequest]:
        now = datetime.now(timezone.utc)
        timeout_expr = func.coalesce(CrawlJob.timeout_at, CrawlJob.lease_expires_at)
        rows = session.execute(
            select(CrawlJob, SourceSite.code)
            .join(SourceSite, SourceSite.id == CrawlJob.source_site_id)
            .where(
                CrawlJob.status == "pending",
                or_(
                    CrawlJob.picked_at.is_(None),
                    timeout_expr.is_(None),
                    timeout_expr <= now,
                ),
            )
            .order_by(CrawlJob.queued_at.asc().nullsfirst(), CrawlJob.id.asc())
            .limit(limit)
        ).all()
        requests: list[CrawlJobDispatchRequest] = []
        for job, source_code in rows:
            requests.append(
                CrawlJobDispatchRequest(
                    source_code=source_code,
                    crawl_job_id=int(job.id),
                    job_type=str(job.job_type),
                    max_pages=read_payload_int(job.job_params_json, "max_pages"),
                    backfill_year=read_payload_int(job.job_params_json, "backfill_year"),
                    triggered_by=str(job.triggered_by).strip() if job.triggered_by is not None else None,
                )
            )
        return requests
