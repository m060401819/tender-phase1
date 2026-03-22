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
from app.repositories import StatsOverviewRecord, StatsRepository
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
    job_trend_map = _to_daily_count_map(_value(payload, "recent_7d_crawl_job_counts", []))
    notice_trend_map = _to_daily_count_map(_value(payload, "recent_7d_notice_counts", []))
    error_trend_map = _to_daily_count_map(_value(payload, "recent_7d_crawl_error_counts", []))
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

    source_count = _safe_int(_value(payload, "source_count", 0))
    active_source_count = _safe_int(_value(payload, "active_source_count", 0))
    crawl_job_count = _safe_int(_value(payload, "crawl_job_count", 0))
    crawl_job_running_count = _safe_int(_value(payload, "crawl_job_running_count", 0))
    notice_count = _safe_int(_value(payload, "notice_count", 0))
    today_new_notice_count = _safe_int(_value(payload, "today_new_notice_count", 0))
    recent_24h_new_notice_count = _safe_int(_value(payload, "recent_24h_new_notice_count", 0))
    raw_document_count = _safe_int(_value(payload, "raw_document_count", 0))
    crawl_error_count = _safe_int(_value(payload, "crawl_error_count", 0))

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
            {
                "id": _safe_int(_value(item, "id", 0)),
                "source_code": str(_value(item, "source_code", "-") or "-"),
                "status": str(_value(item, "status", "-") or "-"),
                "job_type": str(_value(item, "job_type", "-") or "-"),
                "started_at": _fmt_datetime(_value(item, "started_at")),
                "finished_at": _fmt_datetime(_value(item, "finished_at")),
                "error_count": _safe_int(_value(item, "error_count", 0)),
                "message": _value(item, "message"),
            }
            for item in _value(payload, "recent_failed_or_partial_jobs", [])
        ],
        "recent_crawl_errors": [
            {
                "id": _safe_int(_value(item, "id", 0)),
                "source_code": str(_value(item, "source_code", "-") or "-"),
                "crawl_job_id": _safe_int(_value(item, "crawl_job_id", 0))
                if _value(item, "crawl_job_id") is not None
                else None,
                "stage": str(_value(item, "stage", "-") or "-"),
                "error_type": str(_value(item, "error_type", "-") or "-"),
                "message": str(_value(item, "message", "-") or "-"),
                "url": _value(item, "url"),
                "created_at": _fmt_datetime(_value(item, "created_at")),
            }
            for item in _value(payload, "recent_crawl_errors", [])
        ],
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


def _to_daily_count_map(items: Iterable[object]) -> dict[str, int]:
    count_map: dict[str, int] = {}
    for item in items:
        day = str(_value(item, "date", "") or "").strip()
        if not day:
            continue
        count_map[day[:10]] = _safe_int(_value(item, "count", 0))
    return count_map


def _value(item: object, key: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)
