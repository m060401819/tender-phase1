#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings as app_settings  # noqa: E402
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
            spider_args=args.spider_arg,
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

        print(
            "[crawl-job] "
            f"job_id={final.id} status={final.status} "
            f"pages={final.pages_fetched} documents={final.documents_saved} "
            f"notices={final.notices_upserted} dedup={final.deduplicated_count} errors={final.error_count}"
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
