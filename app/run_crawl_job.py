from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.logging import build_log_extra, configure_logging
from app.repositories import SourceSiteRepository
from app.services import CrawlJobService, SourceCrawlTriggerService

LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a queued crawl job in a detached worker process.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source-code", required=True)
    parser.add_argument("--crawl-job-id", required=True, type=int)
    parser.add_argument("--job-type", required=True, choices=["manual", "scheduled", "backfill", "manual_retry"])
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--backfill-year", type=int, default=None)
    return parser


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
                    message=_build_worker_failure_message(
                        source_code=args.source_code,
                        job_type=args.job_type,
                        crawl_job_id=args.crawl_job_id,
                        max_pages=args.max_pages,
                        backfill_year=args.backfill_year,
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
    except Exception as exc:
        LOGGER.exception(
            "crawl worker failed",
            extra=build_log_extra(event="crawl_worker_failed", **log_context),
        )
        crawl_job_service.fail_job_if_active(
            args.crawl_job_id,
            message=_build_worker_failure_message(
                source_code=args.source_code,
                job_type=args.job_type,
                crawl_job_id=args.crawl_job_id,
                max_pages=args.max_pages,
                backfill_year=args.backfill_year,
                failure_reason=f"后台执行失败：{exc}",
            ),
        )
        return 1
    finally:
        engine.dispose()


def _build_worker_failure_message(
    *,
    source_code: str,
    job_type: str,
    crawl_job_id: int,
    max_pages: int | None,
    backfill_year: int | None,
    failure_reason: str,
) -> str:
    parts = [
        f"source_code={source_code}",
        f"job_type={job_type}",
        f"crawl_job_id={int(crawl_job_id)}",
    ]
    if max_pages is not None:
        parts.append(f"max_pages={int(max_pages)}")
    if backfill_year is not None:
        parts.append(f"backfill_year={int(backfill_year)}")
    parts.extend(
        [
            "run_stage=worker_error",
            f"failure_reason={failure_reason}",
        ]
    )
    return "; ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
