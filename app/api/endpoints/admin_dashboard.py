from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.endpoints.stats import get_stats_overview
from app.db.session import get_db

router = APIRouter(tags=["admin-dashboard"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_stats_overview(db=db)

    trend_rows = []
    job_trend_map = {item.date: item.count for item in payload.recent_7d_crawl_job_counts}
    notice_trend_map = {item.date: item.count for item in payload.recent_7d_notice_counts}
    error_trend_map = {item.date: item.count for item in payload.recent_7d_crawl_error_counts}
    dates = sorted(set(job_trend_map) | set(notice_trend_map) | set(error_trend_map))
    for day in dates:
        trend_rows.append(
            {
                "date": day,
                "crawl_job_count": int(job_trend_map.get(day, 0)),
                "notice_count": int(notice_trend_map.get(day, 0)),
                "crawl_error_count": int(error_trend_map.get(day, 0)),
            }
        )

    context = {
        "request": request,
        "counts": {
            "source_count": payload.source_count,
            "active_source_count": payload.active_source_count,
            "crawl_job_count": payload.crawl_job_count,
            "crawl_job_running_count": payload.crawl_job_running_count,
            "notice_count": payload.notice_count,
            "raw_document_count": payload.raw_document_count,
            "crawl_error_count": payload.crawl_error_count,
        },
        "trend_rows": trend_rows,
        "recent_failed_or_partial_jobs": [
            {
                "id": item.id,
                "source_code": item.source_code,
                "status": item.status,
                "job_type": item.job_type,
                "started_at": _fmt_datetime(item.started_at),
                "finished_at": _fmt_datetime(item.finished_at),
                "error_count": item.error_count,
                "message": item.message,
            }
            for item in payload.recent_failed_or_partial_jobs
        ],
        "recent_crawl_errors": [
            {
                "id": item.id,
                "source_code": item.source_code,
                "crawl_job_id": item.crawl_job_id,
                "stage": item.stage,
                "error_type": item.error_type,
                "message": item.message,
                "url": item.url,
                "created_at": _fmt_datetime(item.created_at),
            }
            for item in payload.recent_crawl_errors
        ],
    }
    return TEMPLATES.TemplateResponse(name="admin/dashboard.html", context=context, request=request)


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)
