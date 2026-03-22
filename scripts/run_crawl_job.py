#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings as app_settings  # noqa: E402
from app.models import CrawlError, RawDocument  # noqa: E402
from app.services import CRAWL_JOB_TYPES, CrawlJobService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and run a crawl_job with Scrapy spider")
    parser.add_argument("--spider", required=True, help="Scrapy spider name")
    parser.add_argument("--source-code", help="source_site.code; defaults to spider name")
    parser.add_argument("--source-name", help="source_site.name")
    parser.add_argument("--source-url", help="source_site.base_url")
    parser.add_argument("--job-type", default="manual", choices=sorted(CRAWL_JOB_TYPES))
    parser.add_argument("--triggered-by", default="cli")
    parser.add_argument("--message", default=None)
    parser.add_argument("--database-url", default=None, help="DB URL for crawl_job and sqlalchemy writer")

    parser.add_argument(
        "--writer-backend",
        default="sqlalchemy",
        choices=["sqlalchemy", "jsonl", "noop"],
        help="CRAWLER_WRITER_BACKEND passed to scrapy",
    )
    parser.add_argument(
        "--spider-arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="additional -a KEY=VALUE passed to spider (repeatable)",
    )
    parser.add_argument(
        "--setting",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="additional -s KEY=VALUE passed to scrapy (repeatable)",
    )
    parser.add_argument(
        "--fail-on-partial",
        action="store_true",
        help="exit non-zero when job finished as partial",
    )
    return parser.parse_args()


def resolve_database_url(explicit_url: str | None) -> str:
    return (
        (explicit_url or "").strip()
        or os.getenv("CRAWLER_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
        or app_settings.database_url
    )


def validate_key_value(items: list[str], *, flag: str) -> None:
    for value in items:
        if "=" not in value:
            raise ValueError(f"{flag} must be KEY=VALUE, got: {value}")


def parse_key_value_map(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            continue
        key, value = raw.split("=", maxsplit=1)
        key = key.strip()
        if not key:
            continue
        parsed[key] = value.strip()
    return parsed


def _normalize_iso_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def collect_list_page_stats(*, database_url: str, crawl_job_id: int) -> tuple[int, str | None, str | None]:
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    pages_scraped = 0
    first_publish_date_seen: str | None = None
    last_publish_date_seen: str | None = None

    try:
        with session_factory() as session:
            session = session  # type: Session
            metas = session.scalars(
                select(RawDocument.extra_meta).where(RawDocument.crawl_job_id == crawl_job_id)
            ).all()
            for meta in metas:
                if not isinstance(meta, dict):
                    continue
                if str(meta.get("role") or "").lower() != "list":
                    continue
                pages_scraped += 1

                values = [
                    _normalize_iso_date(meta.get("list_page_publish_date_max")),
                    _normalize_iso_date(meta.get("list_page_publish_date_min")),
                    _normalize_iso_date(meta.get("first_publish_date_seen_total")),
                    _normalize_iso_date(meta.get("last_publish_date_seen_total")),
                ]
                for value in values:
                    if value is None:
                        continue
                    if first_publish_date_seen is None or value > first_publish_date_seen:
                        first_publish_date_seen = value
                    if last_publish_date_seen is None or value < last_publish_date_seen:
                        last_publish_date_seen = value
    except Exception:
        pages_scraped = 0
        first_publish_date_seen = None
        last_publish_date_seen = None
    finally:
        engine.dispose()

    return pages_scraped, first_publish_date_seen, last_publish_date_seen


def infer_failure_reason(
    *,
    database_url: str,
    crawl_job_id: int,
    final_snapshot,
    pages_scraped: int,
    return_code: int,
) -> str:
    if return_code != 0:
        return f"页面获取失败: spider 进程退出({return_code})"

    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        with session_factory() as session:
            rows = session.execute(
                select(CrawlError.stage, CrawlError.error_message).where(CrawlError.crawl_job_id == crawl_job_id)
            ).all()
    except Exception:
        rows = []
    finally:
        engine.dispose()

    fetch_errors = [str(message).strip() for stage, message in rows if str(stage or "").lower() == "fetch" and message]
    parse_errors = [str(message).strip() for stage, message in rows if str(stage or "").lower() == "parse" and message]
    detail_parse_errors = [message for message in parse_errors if "详情" in message or "detail" in message.lower()]

    if fetch_errors and pages_scraped <= 0:
        return f"页面获取失败: {fetch_errors[0]}"
    if fetch_errors and int(final_snapshot.list_items_seen or 0) <= 0:
        return f"页面获取失败: {fetch_errors[0]}"
    if int(final_snapshot.list_items_seen or 0) <= 0:
        return "列表解析为0"
    if detail_parse_errors:
        return f"详情解析失败: {detail_parse_errors[0]}"
    if int(final_snapshot.detail_pages_fetched or 0) <= 0 and parse_errors:
        return f"详情解析失败: {parse_errors[0]}"
    return "-"


def build_job_summary_message(
    *,
    spider: str,
    job_type: str,
    spider_args_map: dict[str, str],
    final_snapshot,
    pages_scraped: int,
    first_publish_date_seen: str | None,
    last_publish_date_seen: str | None,
    failure_reason: str,
) -> str:
    dedup_skipped = int(final_snapshot.list_items_source_duplicates_skipped or 0) + int(
        final_snapshot.source_duplicates_suppressed or 0
    )
    resolved_pages_scraped = pages_scraped if pages_scraped > 0 else int(final_snapshot.pages_fetched or 0)

    parts = [
        f"spider={spider}",
        f"job_type={job_type}",
    ]

    backfill_year = (spider_args_map.get("backfill_year") or "").strip()
    if backfill_year:
        parts.append(f"backfill_year={backfill_year}")

    parts.extend(
        [
            f"pages_scraped={resolved_pages_scraped}",
            f"list_seen={int(final_snapshot.list_items_seen or 0)}",
            f"list_unique={int(final_snapshot.list_items_unique or 0)}",
            f"detail_requests={int(final_snapshot.detail_pages_fetched or 0)}",
            f"dedup_skipped={dedup_skipped}",
            f"notices_written={int(final_snapshot.notices_upserted or 0)}",
            f"raw_documents_written={int(final_snapshot.documents_saved or 0)}",
            f"first_publish_date_seen={first_publish_date_seen or '-'}",
            f"last_publish_date_seen={last_publish_date_seen or '-'}",
            f"failure_reason={failure_reason}",
        ]
    )
    max_pages = (spider_args_map.get("max_pages") or "").strip()
    if max_pages:
        parts.insert(2, f"max_pages={max_pages}")
    return "; ".join(parts)


def build_scrapy_command(
    *,
    spider: str,
    crawl_job_id: int,
    writer_backend: str,
    database_url: str,
    spider_args: list[str],
    settings: list[str],
) -> list[str]:
    command = [sys.executable, "-m", "scrapy", "crawl", spider, "-a", f"crawl_job_id={crawl_job_id}"]

    for arg in spider_args:
        command.extend(["-a", arg])

    command.extend(["-s", f"CRAWLER_WRITER_BACKEND={writer_backend}"])
    if database_url:
        command.extend(["-s", f"CRAWLER_DATABASE_URL={database_url}"])

    for setting in settings:
        command.extend(["-s", setting])

    return command


def main() -> int:
    args = parse_args()
    validate_key_value(args.spider_arg, flag="--spider-arg")
    validate_key_value(args.setting, flag="--setting")
    effective_spider_args = list(args.spider_arg)
    spider_args_map = parse_key_value_map(effective_spider_args)
    if "job_type" not in spider_args_map:
        effective_spider_args.append(f"job_type={args.job_type}")
        spider_args_map["job_type"] = args.job_type

    database_url = resolve_database_url(args.database_url)
    service = CrawlJobService.from_database_url(database_url)

    source_code = (args.source_code or args.spider).strip()

    try:
        job = service.create_job(
            source_code=source_code,
            source_name=args.source_name,
            source_url=args.source_url,
            job_type=args.job_type,
            triggered_by=args.triggered_by,
            message=args.message,
        )
        service.start_job(job.id, message=f"spider={args.spider}")

        command = build_scrapy_command(
            spider=args.spider,
            crawl_job_id=job.id,
            writer_backend=args.writer_backend,
            database_url=database_url,
            spider_args=effective_spider_args,
            settings=args.setting,
        )

        print(f"[crawl-job] created job_id={job.id} source_code={source_code} job_type={args.job_type}")
        print(f"[crawl-job] running command: {' '.join(command)}")

        completed = subprocess.run(command, cwd=PROJECT_ROOT / "crawler", check=False)

        if completed.returncode == 0:
            final = service.finish_job(job.id, status=None, message="scrapy finished")
        else:
            final = service.finish_job(
                job.id,
                status="failed",
                message=f"scrapy exited with code {completed.returncode}",
            )

        if final is None:
            print(f"[crawl-job] job_id={job.id} missing when finalizing", file=sys.stderr)
            return 1

        pages_scraped, first_publish_date_seen, last_publish_date_seen = collect_list_page_stats(
            database_url=database_url,
            crawl_job_id=final.id,
        )
        failure_reason = infer_failure_reason(
            database_url=database_url,
            crawl_job_id=final.id,
            final_snapshot=final,
            pages_scraped=pages_scraped,
            return_code=completed.returncode,
        )
        summary_message = build_job_summary_message(
            spider=args.spider,
            job_type=args.job_type,
            spider_args_map=spider_args_map,
            final_snapshot=final,
            pages_scraped=pages_scraped,
            first_publish_date_seen=first_publish_date_seen,
            last_publish_date_seen=last_publish_date_seen,
            failure_reason=failure_reason,
        )
        refreshed = service.finish_job(
            final.id,
            status=final.status,
            message=summary_message,
        )
        if refreshed is not None:
            final = refreshed

        print(
            "[crawl-job] "
            f"job_id={final.id} status={final.status} "
            f"pages={final.pages_fetched} documents={final.documents_saved} "
            f"notices={final.notices_upserted} dedup={final.deduplicated_count} errors={final.error_count} "
            f"summary=\"{final.message or ''}\""
        )

        if final.status == "failed":
            return completed.returncode or 1
        if args.fail_on_partial and final.status == "partial":
            return 2
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
