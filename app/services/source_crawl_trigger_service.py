from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CrawlError, CrawlJob, RawDocument, SourceSite
from app.services.source_adapter_registry import get_source_adapter, resolve_spider_name, supports_job_type
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
    """Create crawl jobs and trigger crawl execution."""

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
            message_prefix="source api trigger",
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
        self._build_spider_args(max_pages=max_pages, backfill_year=None, job_type="manual")
        return self._create_crawl_job(
            source=source,
            triggered_by=triggered_by,
            job_type="manual",
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
        return self._run_existing_crawl_job(
            source=source,
            crawl_job_id=crawl_job_id,
            job_type="manual",
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=None,
                job_type="manual",
            ),
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
            message_prefix=f"source backfill trigger: backfill_year={backfill_year}",
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
            message_prefix="source schedule trigger",
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
            message_prefix=f"source retry trigger: retry_of_job_id={retry_of_job_id}",
            retry_of_job_id=retry_of_job_id,
            spider_args=self._build_spider_args(
                max_pages=max_pages,
                backfill_year=backfill_year,
                job_type="manual_retry",
            ),
        )

    def _trigger_crawl(
        self,
        *,
        source: SourceSite,
        triggered_by: str,
        job_type: str,
        message_prefix: str,
        retry_of_job_id: int | None = None,
        spider_args: dict[str, str] | None = None,
    ) -> SourceCrawlTriggerResult:
        normalized_spider_args = dict(spider_args or {})
        job = self._create_crawl_job(
            source=source,
            triggered_by=triggered_by,
            job_type=job_type,
            message=f"{message_prefix}: {source.code}",
            retry_of_job_id=retry_of_job_id,
        )
        return self._run_existing_crawl_job(
            source=source,
            crawl_job_id=job.id,
            job_type=job_type,
            spider_args=normalized_spider_args,
        )

    def _create_crawl_job(
        self,
        *,
        source: SourceSite,
        triggered_by: str,
        job_type: str,
        message: str,
        retry_of_job_id: int | None,
    ) -> CrawlJobSnapshot:
        self._resolve_spider_name_for_source(source=source, job_type=job_type)
        job = self.crawl_job_service.create_job_in_session(
            self.session,
            source_code=source.code,
            source_name=source.name,
            source_url=source.base_url,
            job_type=job_type,
            triggered_by=triggered_by,
            retry_of_job_id=retry_of_job_id,
            message=message,
        )
        job_id = int(job.id)
        self.session.commit()
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

        self.crawl_job_service.start_job_in_session(
            self.session,
            job_id=int(crawl_job_id),
            message=f"spider={spider_name}",
        )
        self.session.commit()

        command = self._build_command(
            spider=spider_name,
            crawl_job_id=int(crawl_job_id),
            spider_args=normalized_spider_args,
        )

        try:
            return_code = self.command_runner.run(command, cwd=self.project_root / "crawler")
        except Exception as exc:
            failed_snapshot = self.crawl_job_service.finish_job(
                int(crawl_job_id),
                status="failed",
                message=f"command runner error: {exc}",
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
            message="source api trigger finished" if return_code == 0 else f"spider exited with code {return_code}",
        )
        if finalized is None:
            raise RuntimeError(f"crawl_job not found when finalizing: {crawl_job_id}")
        snapshot = finalized
        final_message = self._build_job_summary_message(
            source_code=source.code,
            job_type=job_type,
            spider_args=normalized_spider_args,
            snapshot=snapshot,
            pages_scraped=pages_scraped,
            first_publish_date_seen=first_publish_date_seen,
            last_publish_date_seen=last_publish_date_seen,
            return_code=return_code,
            crawl_job_id=int(crawl_job_id),
            failure_reason=failure_reason,
        )
        refreshed = self.crawl_job_service.finish_job(
            int(crawl_job_id),
            status=snapshot.status,
            message=final_message,
        )
        if refreshed is not None:
            snapshot = refreshed

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

    def _build_job_summary_message(
        self,
        *,
        source_code: str,
        job_type: str,
        spider_args: dict[str, str],
        snapshot: CrawlJobSnapshot,
        pages_scraped: int,
        first_publish_date_seen: str | None,
        last_publish_date_seen: str | None,
        return_code: int,
        crawl_job_id: int,
        failure_reason: str | None = None,
    ) -> str:
        dedup_skipped = int(snapshot.list_items_source_duplicates_skipped or 0) + int(
            snapshot.source_duplicates_suppressed or 0
        )
        list_seen = int(snapshot.list_items_seen or 0)
        list_unique = int(snapshot.list_items_unique or 0)
        pages_metric = pages_scraped if pages_scraped > 0 else int(snapshot.pages_fetched or 0)
        resolved_failure_reason = (failure_reason or "").strip() or self._infer_failure_reason(
            crawl_job_id=crawl_job_id,
            snapshot=snapshot,
            pages_scraped=pages_metric,
            return_code=return_code,
        )
        summary_parts = [
            f"source_code={source_code}",
            f"job_type={job_type}",
            f"pages_scraped={pages_metric}",
            f"list_seen={list_seen}",
            f"list_unique={list_unique}",
            f"detail_requests={int(snapshot.detail_pages_fetched or 0)}",
            f"dedup_skipped={dedup_skipped}",
            f"notices_written={int(snapshot.notices_upserted or 0)}",
            f"raw_documents_written={int(snapshot.documents_saved or 0)}",
            f"first_publish_date_seen={first_publish_date_seen or '-'}",
            f"last_publish_date_seen={last_publish_date_seen or '-'}",
            f"failure_reason={resolved_failure_reason}",
        ]
        backfill_year = (spider_args.get("backfill_year") or "").strip()
        if backfill_year:
            summary_parts.insert(2, f"backfill_year={backfill_year}")
        max_pages = (spider_args.get("max_pages") or "").strip()
        if max_pages:
            summary_parts.insert(2, f"max_pages={max_pages}")
        if return_code != 0:
            summary_parts.append(f"return_code={return_code}")
        return "; ".join(summary_parts)

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


def _database_url_for_bind(bind: object) -> str:
    url = getattr(bind, "url", None)
    if url is None:
        raise RuntimeError("database bind url is required")
    render_as_string = getattr(url, "render_as_string", None)
    if callable(render_as_string):
        return str(render_as_string(hide_password=False))
    return str(url)
