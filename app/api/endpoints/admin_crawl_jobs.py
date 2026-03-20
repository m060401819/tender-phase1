from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.endpoints.crawl_jobs import get_crawl_job, list_crawl_jobs
from app.api.schemas import CrawlJobOrderBy, CrawlJobStatus, CrawlJobType
from app.db.session import get_db

router = APIRouter(tags=["admin-crawl-jobs"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


@router.get("/admin/crawl-jobs", response_class=HTMLResponse)
def admin_crawl_jobs_list(
    request: Request,
    source_code: str | None = Query(default=None),
    status: CrawlJobStatus | None = Query(default=None),
    job_type: CrawlJobType | None = Query(default=None),
    order_by: CrawlJobOrderBy = Query(default=CrawlJobOrderBy.started_at),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = list_crawl_jobs(
        source_code=source_code,
        status=status,
        job_type=job_type,
        order_by=order_by,
        limit=limit,
        offset=offset,
        db=db,
    )

    total = payload.total
    has_prev = offset > 0
    has_next = offset + limit < total

    prev_offset = max(offset - limit, 0)
    next_offset = offset + limit

    common_query: dict[str, Any] = {
        "source_code": source_code,
        "status": status.value if status else None,
        "job_type": job_type.value if job_type else None,
        "order_by": order_by.value,
        "limit": limit,
    }

    prev_url = _admin_list_url(common_query, prev_offset) if has_prev else None
    next_url = _admin_list_url(common_query, next_offset) if has_next else None

    jobs = [_list_item_to_dict(item) for item in payload.items]

    context = {
        "request": request,
        "jobs": jobs,
        "source_code": source_code or "",
        "status": status.value if status else "",
        "job_type": job_type.value if job_type else "",
        "order_by": order_by.value,
        "limit": limit,
        "offset": offset,
        "total": total,
        "prev_url": prev_url,
        "next_url": next_url,
        "status_options": ["pending", "running", "succeeded", "failed", "partial"],
        "job_type_options": ["manual", "scheduled", "backfill"],
    }
    return TEMPLATES.TemplateResponse(name="admin/crawl_jobs_list.html", context=context, request=request)


@router.get("/admin/crawl-jobs/{job_id}", response_class=HTMLResponse)
def admin_crawl_job_detail(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_crawl_job(job_id=job_id, db=db)

    job_dict = {
        "id": payload.id,
        "source_site_id": payload.source_site_id,
        "source_code": payload.source_code,
        "job_type": payload.job_type,
        "status": payload.status,
        "started_at": _fmt_datetime(payload.started_at),
        "finished_at": _fmt_datetime(payload.finished_at),
        "pages_fetched": payload.pages_fetched,
        "documents_saved": payload.documents_saved,
        "notices_upserted": payload.notices_upserted,
        "deduplicated_count": payload.deduplicated_count,
        "error_count": payload.error_count,
        "recent_crawl_error_count": payload.recent_crawl_error_count,
        "message": payload.message,
    }

    raw_json = json.dumps(
        {
            "id": payload.id,
            "source_site_id": payload.source_site_id,
            "source_code": payload.source_code,
            "job_type": payload.job_type,
            "status": payload.status,
            "started_at": payload.started_at.isoformat() if payload.started_at else None,
            "finished_at": payload.finished_at.isoformat() if payload.finished_at else None,
            "pages_fetched": payload.pages_fetched,
            "documents_saved": payload.documents_saved,
            "notices_upserted": payload.notices_upserted,
            "deduplicated_count": payload.deduplicated_count,
            "error_count": payload.error_count,
            "recent_crawl_error_count": payload.recent_crawl_error_count,
            "message": payload.message,
        },
        ensure_ascii=False,
        indent=2,
    )

    context = {
        "request": request,
        "job": job_dict,
        "raw_json": raw_json,
    }
    return TEMPLATES.TemplateResponse(name="admin/crawl_jobs_detail.html", context=context, request=request)


def _admin_list_url(common_query: dict[str, Any], offset: int) -> str:
    params = dict(common_query)
    params["offset"] = offset
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"/admin/crawl-jobs?{urlencode(clean)}"


def _list_item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_code": item.source_code,
        "job_type": item.job_type,
        "status": item.status,
        "started_at": _fmt_datetime(item.started_at),
        "finished_at": _fmt_datetime(item.finished_at),
        "pages_fetched": item.pages_fetched,
        "documents_saved": item.documents_saved,
        "notices_upserted": item.notices_upserted,
        "deduplicated_count": item.deduplicated_count,
        "error_count": item.error_count,
    }


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)
