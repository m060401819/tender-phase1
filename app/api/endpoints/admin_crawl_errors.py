from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.endpoints.crawl_errors import get_crawl_error_detail
from app.api.schemas import CrawlErrorStage
from app.db.session import get_db
from app.repositories import CrawlErrorRepository
from app.services import CrawlErrorQueryService, SourceOpsService

router = APIRouter(tags=["admin-crawl-errors"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


@router.get("/admin/crawl-errors", response_class=HTMLResponse)
def admin_crawl_errors_list(
    request: Request,
    source_code: str | None = Query(default=None),
    stage: CrawlErrorStage | None = Query(default=None),
    crawl_job_id: int | None = Query(default=None, ge=1),
    error_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    service = CrawlErrorQueryService(repository=CrawlErrorRepository(db))
    payload = service.list_crawl_errors(
        source_code=source_code,
        stage=stage.value if stage else None,
        crawl_job_id=crawl_job_id,
        error_type=error_type,
        limit=limit,
        offset=offset,
    )
    source_summaries = service.list_recent_source_summaries(
        source_code=source_code,
        stage=stage.value if stage else None,
        crawl_job_id=crawl_job_id,
        error_type=error_type,
        recent_days=7,
        limit=10,
    )
    summary_source_codes = [item.source_code for item in source_summaries]
    source_ops_map = {
        item.source_code: item
        for item in SourceOpsService(session=db).list_source_ops(recent_hours=24, source_codes=summary_source_codes)
    }

    total = payload.total
    has_prev = offset > 0
    has_next = offset + limit < total

    prev_offset = max(offset - limit, 0)
    next_offset = offset + limit

    common_query: dict[str, Any] = {
        "source_code": source_code,
        "stage": stage.value if stage else None,
        "crawl_job_id": crawl_job_id,
        "error_type": error_type,
        "limit": limit,
    }
    prev_url = _admin_list_url(common_query, prev_offset) if has_prev else None
    next_url = _admin_list_url(common_query, next_offset) if has_next else None

    context = {
        "request": request,
        "errors": [_list_item_to_dict(item) for item in payload.items],
        "source_code": source_code or "",
        "stage": stage.value if stage else "",
        "crawl_job_id": crawl_job_id or "",
        "error_type": error_type or "",
        "limit": limit,
        "offset": offset,
        "total": total,
        "prev_url": prev_url,
        "next_url": next_url,
        "stage_options": ["fetch", "parse", "persist"],
        "source_summaries": [
            {
                "source_code": item.source_code,
                "recent_error_count": item.recent_error_count,
                "latest_error_id": item.latest_error_id,
                "latest_error_message": item.latest_error_message,
                "latest_error_created_at": _fmt_datetime(item.latest_error_created_at),
                "last_retry_status": (
                    source_ops_map[item.source_code].last_retry_status
                    if item.source_code in source_ops_map
                    else None
                ),
                "last_retry_job_id": (
                    source_ops_map[item.source_code].last_retry_job_id
                    if item.source_code in source_ops_map
                    else None
                ),
            }
            for item in source_summaries
        ],
    }
    return TEMPLATES.TemplateResponse(name="admin/crawl_errors_list.html", context=context, request=request)


@router.get("/admin/crawl-errors/{error_id}", response_class=HTMLResponse)
def admin_crawl_error_detail(
    error_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_crawl_error_detail(error_id=error_id, db=db)
    source_ops = SourceOpsService(session=db).get_source_ops(source_code=payload.source_code, recent_hours=24)

    error_dict = {
        "id": payload.id,
        "source_code": payload.source_code,
        "crawl_job_id": payload.crawl_job_id,
        "stage": payload.stage,
        "error_type": payload.error_type,
        "message": payload.message,
        "detail": payload.detail,
        "url": payload.url,
        "traceback": payload.traceback,
        "created_at": _fmt_datetime(payload.created_at),
    }
    context = {
        "request": request,
        "error": error_dict,
        "latest_retry": {
            "status": source_ops.last_retry_status if source_ops is not None else None,
            "job_id": source_ops.last_retry_job_id if source_ops is not None else None,
        },
        "raw_document": (
            {
                "id": payload.raw_document.id,
                "document_type": payload.raw_document.document_type,
                "fetched_at": _fmt_datetime(payload.raw_document.fetched_at),
                "storage_uri": payload.raw_document.storage_uri,
            }
            if payload.raw_document is not None
            else None
        ),
        "notice": (
            {
                "id": payload.notice.id,
                "source_code": payload.notice.source_code,
                "title": payload.notice.title,
                "notice_type": payload.notice.notice_type,
                "current_version_id": payload.notice.current_version_id,
            }
            if payload.notice is not None
            else None
        ),
        "notice_version": (
            {
                "id": payload.notice_version.id,
                "notice_id": payload.notice_version.notice_id,
                "version_no": payload.notice_version.version_no,
                "is_current": payload.notice_version.is_current,
                "title": payload.notice_version.title,
                "notice_type": payload.notice_version.notice_type,
            }
            if payload.notice_version is not None
            else None
        ),
        "raw_json": json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
    }
    return TEMPLATES.TemplateResponse(name="admin/crawl_errors_detail.html", context=context, request=request)


def _admin_list_url(common_query: dict[str, Any], offset: int) -> str:
    params = dict(common_query)
    params["offset"] = offset
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"/admin/crawl-errors?{urlencode(clean)}"


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _list_item_to_dict(item: Any) -> dict[str, Any]:
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
