from __future__ import annotations

import argparse
import logging
import re
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.logging import build_log_extra, configure_logging
from app.repositories import SourceSiteRepository
from app.services.crawl_job_payloads import build_job_params_payload, build_runtime_stats_payload
from app.services import CrawlJobService, CrawlJobStartConflictError, SourceCrawlTriggerService

LOGGER = logging.getLogger(__name__)
_SOURCE_CODE_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a queued crawl job in a detached worker process.")
    parser.add_argument("--database-url", required=True, type=_database_url_arg)
    parser.add_argument("--source-code", required=True, type=_source_code_arg)
    parser.add_argument("--crawl-job-id", required=True, type=int)
    parser.add_argument("--job-type", required=True, choices=["manual", "scheduled", "backfill", "manual_retry"])
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--backfill-year", type=int, default=None)
    return parser


def _database_url_arg(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise argparse.ArgumentTypeError("database-url must not be empty")
    if any(char in text for char in ("\x00", "\r", "\n")):
        raise argparse.ArgumentTypeError("database-url contains unsupported control characters")
    return text


def _source_code_arg(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise argparse.ArgumentTypeError("source-code must not be empty")
    if not _SOURCE_CODE_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError("source-code contains unsupported characters")
    return text


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(level=settings.log_level_value)

    engine = create_engine(args.database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    crawl_job_service = CrawlJobService(session_factory=session_factory)
    job_snapshot = crawl_job_service.get_job(args.crawl_job_id)
    triggered_by = job_snapshot.triggered_by if job_snapshot is not None else None
    log_context = {
        "source_code": args.source_code,
        "crawl_job_id": args.crawl_job_id,
        "job_type": args.job_type,
        "triggered_by": triggered_by,
        "max_pages": args.max_pages,
        "backfill_year": args.backfill_year,
    }

    LOGGER.info(
        "crawl worker started",
        extra=build_log_extra(event="crawl_worker_started", **log_context),
    )

    try:
        with session_factory() as session:
            source = SourceSiteRepository(session).get_model_by_code(args.source_code)
            if source is None:
                LOGGER.error(
                    "crawl worker source missing",
                    extra=build_log_extra(event="crawl_worker_source_missing", **log_context),
                )
                crawl_job_service.fail_job_if_active(
                    args.crawl_job_id,
                    job_params_json=build_job_params_payload(
                        source_code=args.source_code,
                        job_type=args.job_type,
                        triggered_by=triggered_by,
                        max_pages=args.max_pages,
                        backfill_year=args.backfill_year,
                    ),
                    runtime_stats_json=build_runtime_stats_payload(run_stage="worker_error"),
                    failure_reason="后台执行启动失败：来源不存在或已被删除",
                    message=_build_worker_failure_message(
                        job_type=args.job_type,
                        failure_reason="后台执行启动失败：来源不存在或已被删除",
                    ),
                )
                return 1

            trigger_service = SourceCrawlTriggerService(session=session)
            trigger_service.execute_crawl_job(
                source=source,
                crawl_job_id=args.crawl_job_id,
                job_type=args.job_type,
                max_pages=args.max_pages,
                backfill_year=args.backfill_year,
            )
        LOGGER.info(
            "crawl worker finished",
            extra=build_log_extra(event="crawl_worker_finished", **log_context),
        )
        return 0
    except CrawlJobStartConflictError as exc:
        LOGGER.info(
            "crawl worker skipped because job is no longer claimable",
            extra=build_log_extra(
                event="crawl_worker_skipped",
                current_status=exc.current_status,
                failure_reason=str(exc),
                **log_context,
            ),
        )
        return 0
    except Exception as exc:
        LOGGER.exception(
            "crawl worker failed",
            extra=build_log_extra(event="crawl_worker_failed", **log_context),
        )
        crawl_job_service.fail_job_if_active(
            args.crawl_job_id,
            job_params_json=build_job_params_payload(
                source_code=args.source_code,
                job_type=args.job_type,
                triggered_by=triggered_by,
                max_pages=args.max_pages,
                backfill_year=args.backfill_year,
            ),
            runtime_stats_json=build_runtime_stats_payload(run_stage="worker_error"),
            failure_reason=f"后台执行失败：{exc}",
            message=_build_worker_failure_message(
                job_type=args.job_type,
                failure_reason=f"后台执行失败：{exc}",
            ),
        )
        return 1
    finally:
        engine.dispose()


def _build_worker_failure_message(
    *,
    job_type: str,
    failure_reason: str,
) -> str:
    return f"{job_type} 任务执行失败：{failure_reason}"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
