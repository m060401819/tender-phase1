from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.models import SourceSite
from app.services.crawl_job_service import CrawlJobService, CrawlJobSnapshot


class CrawlCommandRunner(Protocol):
    def run(self, command: list[str], *, cwd: Path) -> int:
        """Run crawl command and return process exit code."""


class SubprocessCrawlCommandRunner:
    def run(self, command: list[str], *, cwd: Path) -> int:
        completed = subprocess.run(command, cwd=cwd, check=False)
        return int(completed.returncode)


@dataclass(slots=True)
class SourceCrawlTriggerResult:
    job: CrawlJobSnapshot
    command: list[str]
    return_code: int


class SourceCrawlTriggerService:
    """Create manual crawl_job and trigger one synchronous crawl execution."""

    def __init__(
        self,
        *,
        session: Session,
        command_runner: CrawlCommandRunner | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.session = session
        self.command_runner = command_runner or SubprocessCrawlCommandRunner()
        self.project_root = project_root or Path(__file__).resolve().parents[2]

        bind = self.session.get_bind()
        if bind is None:
            raise RuntimeError("database bind is required")
        self.database_url = str(bind.url)
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
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be >= 1")

        job = self.crawl_job_service.create_job_in_session(
            self.session,
            source_code=source.code,
            source_name=source.name,
            source_url=source.base_url,
            job_type="manual",
            triggered_by=triggered_by,
            message=f"source api trigger: {source.code}",
        )
        job_id = int(job.id)
        self.session.commit()

        self.crawl_job_service.start_job_in_session(
            self.session,
            job_id=job_id,
            message=f"spider={source.code}",
        )
        self.session.commit()

        command = self._build_command(
            spider=source.code,
            crawl_job_id=job_id,
            max_pages=max_pages,
        )

        try:
            return_code = self.command_runner.run(command, cwd=self.project_root / "crawler")
        except Exception as exc:
            self.crawl_job_service.finish_job_in_session(
                self.session,
                job_id=job_id,
                status="failed",
                message=f"command runner error: {exc}",
            )
            self.session.commit()
            raise

        if return_code == 0:
            self.crawl_job_service.finish_job_in_session(
                self.session,
                job_id=job_id,
                status=None,
                message="source api trigger finished",
            )
        else:
            self.crawl_job_service.finish_job_in_session(
                self.session,
                job_id=job_id,
                status="failed",
                message=f"spider exited with code {return_code}",
            )
        self.session.commit()

        snapshot = self.crawl_job_service.get_job(job_id)
        if snapshot is None:
            raise RuntimeError(f"crawl_job not found after trigger: {job_id}")

        return SourceCrawlTriggerResult(
            job=snapshot,
            command=command,
            return_code=return_code,
        )

    def _build_command(self, *, spider: str, crawl_job_id: int, max_pages: int | None) -> list[str]:
        command = [
            sys.executable,
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
        if max_pages is not None:
            command.extend(["-a", f"max_pages={max_pages}"])
        return command
