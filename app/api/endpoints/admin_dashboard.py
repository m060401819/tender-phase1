from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import (
    DailyCountRecord,
    RecentCrawlErrorSummaryRecord,
    RecentJobSummaryRecord,
    StatsOverviewRecord,
    StatsRepository,
)
from app.services import StatsService

router = APIRouter(tags=["admin-dashboard"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
LOGGER = logging.getLogger(__name__)


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_admin_home(request=request, db=db)


@router.get("/admin/home", response_class=HTMLResponse)
def admin_home(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_admin_home(request=request, db=db)


def _render_admin_home(
    *,
    request: Request,
    db: Session,
) -> HTMLResponse:
    payload, dashboard_warning = _load_dashboard_payload(db=db)

    trend_rows = []
    job_trend_map = _to_daily_count_map(payload.recent_7d_crawl_job_counts)
    notice_trend_map = _to_daily_count_map(payload.recent_7d_notice_counts)
    error_trend_map = _to_daily_count_map(payload.recent_7d_crawl_error_counts)
    dates = sorted(set(job_trend_map) | set(notice_trend_map) | set(error_trend_map))
    for day in dates:
        trend_rows.append(
            {
                "date": day,
                "crawl_job_count": _safe_int(job_trend_map.get(day, 0)),
                "notice_count": _safe_int(notice_trend_map.get(day, 0)),
                "crawl_error_count": _safe_int(error_trend_map.get(day, 0)),
            }
        )

    source_count = payload.source_count
    active_source_count = payload.active_source_count
    crawl_job_count = payload.crawl_job_count
    crawl_job_running_count = payload.crawl_job_running_count
    notice_count = payload.notice_count
    today_new_notice_count = payload.today_new_notice_count
    recent_24h_new_notice_count = payload.recent_24h_new_notice_count
    raw_document_count = payload.raw_document_count
    crawl_error_count = payload.crawl_error_count

    context = {
        "request": request,
        "counts": {
            "source_count": source_count,
            "active_source_count": active_source_count,
            "crawl_job_count": crawl_job_count,
            "crawl_job_running_count": crawl_job_running_count,
            "notice_count": notice_count,
            "today_new_notice_count": today_new_notice_count,
            "recent_24h_new_notice_count": recent_24h_new_notice_count,
            "raw_document_count": raw_document_count,
            "crawl_error_count": crawl_error_count,
        },
        "recent_24h_new_notices": recent_24h_new_notice_count,
        "today_new_notices": today_new_notice_count,
        "show_new_notice_alert": recent_24h_new_notice_count > 0,
        "dashboard_warning": dashboard_warning,
        "trend_rows": trend_rows,
        "recent_failed_or_partial_jobs": [
            _to_recent_failed_job_dict(item) for item in payload.recent_failed_or_partial_jobs
        ],
        "recent_crawl_errors": [_to_recent_crawl_error_dict(item) for item in payload.recent_crawl_errors],
    }
    return TEMPLATES.TemplateResponse(name="admin/dashboard.html", context=context, request=request)


def _load_dashboard_payload(*, db: Session) -> tuple[StatsOverviewRecord, str | None]:
    try:
        payload = StatsService(repository=StatsRepository(db)).get_overview()
        return payload, None
    except SQLAlchemyError:
        db.rollback()
        LOGGER.exception("dashboard stats query failed; fallback to defaults")
        return _empty_overview(), "统计数据暂不可用，已降级为默认值。请确认已执行 alembic upgrade head。"
    except Exception:
        db.rollback()
        LOGGER.exception("dashboard rendering failed unexpectedly; fallback to defaults")
        return _empty_overview(), "统计数据暂不可用，已降级为默认值。"


def _empty_overview() -> StatsOverviewRecord:
    return StatsOverviewRecord(
        source_count=0,
        active_source_count=0,
        crawl_job_count=0,
        crawl_job_running_count=0,
        notice_count=0,
        today_new_notice_count=0,
        recent_24h_new_notice_count=0,
        raw_document_count=0,
        crawl_error_count=0,
        recent_7d_crawl_job_counts=[],
        recent_7d_notice_counts=[],
        recent_7d_crawl_error_counts=[],
        recent_failed_or_partial_jobs=[],
        recent_crawl_errors=[],
    )


def _to_daily_count_map(items: Iterable[DailyCountRecord]) -> dict[str, int]:
    count_map: dict[str, int] = {}
    for item in items:
        day = item.date.strip()
        if not day:
            continue
        count_map[day[:10]] = item.count
    return count_map


def _to_recent_failed_job_dict(item: RecentJobSummaryRecord) -> dict[str, object]:
    return {
        "id": item.id,
        "source_code": item.source_code,
        "status": item.status,
        "job_type": item.job_type,
        "started_at": _fmt_datetime(item.started_at),
        "finished_at": _fmt_datetime(item.finished_at),
        "error_count": item.error_count,
        "message": item.message,
    }


def _to_recent_crawl_error_dict(item: RecentCrawlErrorSummaryRecord) -> dict[str, object]:
    return {
        "id": item.id,
        "source_code": item.source_code,
        "crawl_job_id": item.crawl_job_id,
        "stage": item.stage,
        "error_type": item.error_type,
        "message": item.message,
        "url": item.url,
        "created_at": _fmt_datetime(item.created_at),
    }


def _safe_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return 0
    if isinstance(value, (bytes, bytearray)):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)
