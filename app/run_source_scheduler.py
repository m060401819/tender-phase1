from __future__ import annotations

import argparse
import logging
import signal
import sys
from threading import Event

from app.core.config import settings
from app.core.logging import build_log_extra, configure_logging
from app.services import initialize_source_schedule_runtime, shutdown_source_schedule_runtime

LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone source scheduler process.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--refresh-interval-seconds", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(level=settings.log_level_value)

    stop_event = Event()

    def _handle_signal(signum: int, _frame) -> None:
        LOGGER.info(
            "received signal, shutting down standalone scheduler",
            extra=build_log_extra(
                event="standalone_source_scheduler_signal_received",
                job_type="scheduled",
                triggered_by="standalone_scheduler",
                signal=signum,
            ),
        )
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    database_url = args.database_url or settings.database_url
    refresh_interval_seconds = args.refresh_interval_seconds or settings.source_scheduler_refresh_interval_seconds
    runtime = initialize_source_schedule_runtime(
        database_url,
        refresh_interval_seconds=refresh_interval_seconds,
    )

    LOGGER.info(
        "starting standalone scheduler",
        extra=build_log_extra(
            event="standalone_source_scheduler_starting",
            job_type="scheduled",
            triggered_by="standalone_scheduler",
            refresh_interval_seconds=refresh_interval_seconds,
            database_url_configured=bool(database_url),
        ),
    )
    try:
        runtime.start()
        stop_event.wait()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        LOGGER.exception(
            "standalone scheduler crashed during startup or execution",
            extra=build_log_extra(
                event="standalone_source_scheduler_crashed",
                job_type="scheduled",
                triggered_by="standalone_scheduler",
            ),
        )
        return 1
    finally:
        shutdown_source_schedule_runtime()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
