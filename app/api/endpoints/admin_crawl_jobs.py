from __future__ import annotations

from datetime import datetime, time, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.endpoints.crawl_jobs import get_crawl_job, retry_crawl_job
from app.api.endpoints.sources import get_source_crawl_trigger_service
from app.api.schemas import CrawlJobOrderBy, CrawlJobRetryRequest, CrawlJobStatus, CrawlJobType
from app.db.session import get_db
from app.repositories import CrawlJobRepository
from app.services import CrawlJobQueryService, SourceCrawlTriggerService
from app.services.crawl_job_progress_service import build_crawl_job_progress

router = APIRouter(tags=["admin-crawl-jobs"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
OPS_FILTER_OPTIONS = {"abnormal", "today_failed", "partial"}


@router.get("/admin/crawl-jobs", response_class=HTMLResponse)
def admin_crawl_jobs_list(
    request: Request,
    source_code: str | None = Query(default=None),
    status: CrawlJobStatus | None = Query(default=None),
    job_type: CrawlJobType | None = Query(default=None),
    ops_filter: str | None = Query(default=None),
    order_by: CrawlJobOrderBy = Query(default=CrawlJobOrderBy.started_at),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    repository = CrawlJobRepository(db)
    normalized_ops_filter = ops_filter if ops_filter in OPS_FILTER_OPTIONS else ""
    effective_status, status_in, started_from = _resolve_ops_filter(
        status=status.value if status else None,
        ops_filter=normalized_ops_filter or None,
    )

    payload = CrawlJobQueryService(repository=repository).list_crawl_jobs(
        source_code=source_code,
        status=effective_status,
        job_type=job_type.value if job_type else None,
        status_in=status_in,
        started_from=started_from,
        order_by=order_by.value,
        limit=limit,
        offset=offset,
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
        "ops_filter": normalized_ops_filter or None,
        "order_by": order_by.value,
        "limit": limit,
    }

    prev_url = _admin_list_url(common_query, prev_offset) if has_prev else None
    next_url = _admin_list_url(common_query, next_offset) if has_next else None

    jobs = [_list_item_to_dict(item) for item in payload.items]
    active_job_count = sum(1 for job in jobs if job["is_active"])
    created_job_id_raw = request.query_params.get("created_job_id", "")
    retry_created_job_id_raw = request.query_params.get("retry_created_job_id", "")
    created_job = _load_job_banner(repository=repository, job_id=_as_int(created_job_id_raw))
    retry_created_job = _load_job_banner(repository=repository, job_id=_as_int(retry_created_job_id_raw))
    polling_enabled = bool(
        active_job_count
        or (created_job is not None and bool(created_job["is_active"]))
        or (retry_created_job is not None and bool(retry_created_job["is_active"]))
    )

    context = {
        "request": request,
        "jobs": jobs,
        "source_code": source_code or "",
        "status": status.value if status else "",
        "job_type": job_type.value if job_type else "",
        "ops_filter": normalized_ops_filter,
        "order_by": order_by.value,
        "limit": limit,
        "offset": offset,
        "total": total,
        "prev_url": prev_url,
        "next_url": next_url,
        "status_options": ["pending", "running", "succeeded", "failed", "partial"],
        "job_type_options": ["manual", "scheduled", "backfill", "manual_retry"],
        "ops_filter_options": [
            ("", "运营视图：全部"),
            ("abnormal", "仅看异常"),
            ("today_failed", "仅看今日失败"),
            ("partial", "仅看 partial"),
        ],
        "retry_created_job_id": retry_created_job_id_raw,
        "created_job_id": created_job_id_raw,
        "created_job": created_job,
        "retry_created_job": retry_created_job,
        "active_job_count": active_job_count,
        "polling_enabled": polling_enabled,
        "auto_refresh_interval_seconds": 5,
    }
    return TEMPLATES.TemplateResponse(name="admin/crawl_jobs_list.html", context=context, request=request)


@router.post("/admin/crawl-jobs/{job_id}/retry")
def admin_retry_crawl_job(
    job_id: int,
    db: Session = Depends(get_db),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
):
    try:
        result = retry_crawl_job(
            job_id=job_id,
            payload=CrawlJobRetryRequest(triggered_by="admin-retry"),
            db=db,
            trigger_service=trigger_service,
        )
    except HTTPException as exc:
        raise exc
    return RedirectResponse(url=f"/admin/crawl-jobs?retry_created_job_id={result.retry_job.id}", status_code=303)


@router.get("/admin/crawl-jobs/{job_id}", response_class=HTMLResponse)
def admin_crawl_job_detail(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_crawl_job(job_id=job_id, db=db)
    normalized_job_type = _enum_text(payload.job_type)
    normalized_status = _enum_text(payload.status)
    normalized_retried_by_status = _enum_text(payload.retried_by_status)
    message_fields = _parse_message_key_values(payload.message)
    dedup_skipped = int(payload.list_items_source_duplicates_skipped or 0) + int(payload.source_duplicates_suppressed or 0)
    pages_scraped = _as_int(message_fields.get("pages_scraped")) or payload.pages_fetched

    list_seen = _as_int(message_fields.get("list_seen")) or payload.list_items_seen
    list_unique = _as_int(message_fields.get("list_unique")) or payload.list_items_unique
    job_dict = {
        "id": payload.id,
        "source_site_id": payload.source_site_id,
        "source_code": payload.source_code,
        "job_type": normalized_job_type,
        "status": normalized_status,
        "retry_of_job_id": payload.retry_of_job_id,
        "retry_of_job_message": payload.retry_of_job_message,
        "retried_by_job_id": payload.retried_by_job_id,
        "retried_by_status": normalized_retried_by_status,
        "retried_by_finished_at": _fmt_datetime(payload.retried_by_finished_at),
        "retried_by_message": payload.retried_by_message,
        "started_at": _fmt_datetime(payload.started_at),
        "finished_at": _fmt_datetime(payload.finished_at),
        "pages_fetched": payload.pages_fetched,
        "documents_saved": payload.documents_saved,
        "notices_upserted": payload.notices_upserted,
        "deduplicated_count": payload.deduplicated_count,
        "error_count": payload.error_count,
        "list_items_seen": payload.list_items_seen,
        "list_items_unique": payload.list_items_unique,
        "list_seen": list_seen,
        "list_unique": list_unique,
        "list_items_source_duplicates_skipped": payload.list_items_source_duplicates_skipped,
        "detail_pages_fetched": payload.detail_pages_fetched,
        "records_inserted": payload.records_inserted,
        "records_updated": payload.records_updated,
        "source_duplicates_suppressed": payload.source_duplicates_suppressed,
        "pages_scraped": pages_scraped,
        "detail_requests": _as_int(message_fields.get("detail_requests")) or payload.detail_pages_fetched,
        "dedup_skipped": _as_int(message_fields.get("dedup_skipped")) or dedup_skipped,
        "notices_written": _as_int(message_fields.get("notices_written")) or payload.notices_upserted,
        "raw_documents_written": _as_int(message_fields.get("raw_documents_written")) or payload.documents_saved,
        "backfill_year": message_fields.get("backfill_year"),
        "first_publish_date_seen": message_fields.get("first_publish_date_seen"),
        "last_publish_date_seen": message_fields.get("last_publish_date_seen"),
        "failure_reason": message_fields.get("failure_reason"),
        "recent_crawl_error_count": payload.recent_crawl_error_count,
        "message": payload.message,
    }
    progress = build_crawl_job_progress(payload)
    job_dict.update(
        {
            "is_active": bool(progress["is_active"]),
            "job_type_label": progress["job_type_label"],
            "status_label": progress["status_label"],
            "progress_stage_label": progress["stage_label"],
            "progress_summary": progress["summary_text"],
        }
    )

    raw_json = json.dumps(
        {
            "id": payload.id,
            "source_site_id": payload.source_site_id,
            "source_code": payload.source_code,
            "job_type": payload.job_type,
            "status": payload.status,
            "retry_of_job_id": payload.retry_of_job_id,
            "retry_of_job_message": payload.retry_of_job_message,
            "retried_by_job_id": payload.retried_by_job_id,
            "retried_by_status": payload.retried_by_status,
            "retried_by_finished_at": payload.retried_by_finished_at.isoformat() if payload.retried_by_finished_at else None,
            "retried_by_message": payload.retried_by_message,
            "started_at": payload.started_at.isoformat() if payload.started_at else None,
            "finished_at": payload.finished_at.isoformat() if payload.finished_at else None,
            "pages_fetched": payload.pages_fetched,
            "documents_saved": payload.documents_saved,
            "notices_upserted": payload.notices_upserted,
            "deduplicated_count": payload.deduplicated_count,
            "error_count": payload.error_count,
            "list_items_seen": payload.list_items_seen,
            "list_items_unique": payload.list_items_unique,
            "list_seen": list_seen,
            "list_unique": list_unique,
            "list_items_source_duplicates_skipped": payload.list_items_source_duplicates_skipped,
            "detail_pages_fetched": payload.detail_pages_fetched,
            "records_inserted": payload.records_inserted,
            "records_updated": payload.records_updated,
            "source_duplicates_suppressed": payload.source_duplicates_suppressed,
            "pages_scraped": pages_scraped,
            "detail_requests": _as_int(message_fields.get("detail_requests")) or payload.detail_pages_fetched,
            "dedup_skipped": _as_int(message_fields.get("dedup_skipped")) or dedup_skipped,
            "notices_written": _as_int(message_fields.get("notices_written")) or payload.notices_upserted,
            "raw_documents_written": _as_int(message_fields.get("raw_documents_written")) or payload.documents_saved,
            "backfill_year": message_fields.get("backfill_year"),
            "first_publish_date_seen": message_fields.get("first_publish_date_seen"),
            "last_publish_date_seen": message_fields.get("last_publish_date_seen"),
            "failure_reason": message_fields.get("failure_reason"),
            "recent_crawl_error_count": payload.recent_crawl_error_count,
            "message": payload.message,
        },
        ensure_ascii=False,
        indent=2,
    )

    context = {
        "request": request,
        "job": job_dict,
        "can_retry": normalized_status in {"failed", "partial"}
        and payload.retry_of_job_id is None
        and payload.retried_by_job_id is None,
        "created_job_id": request.query_params.get("created_job_id", ""),
        "raw_json": raw_json,
        "auto_refresh_interval_seconds": 3,
    }
    return TEMPLATES.TemplateResponse(name="admin/crawl_jobs_detail.html", context=context, request=request)


def _admin_list_url(common_query: dict[str, Any], offset: int) -> str:
    params = dict(common_query)
    params["offset"] = offset
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"/admin/crawl-jobs?{urlencode(clean)}"


def _list_item_to_dict(item: Any) -> dict[str, Any]:
    payload = {
        "id": item.id,
        "source_code": item.source_code,
        "job_type": item.job_type,
        "status": item.status,
        "retry_of_job_id": item.retry_of_job_id,
        "retry_of_job_message": item.retry_of_job_message,
        "retried_by_job_id": item.retried_by_job_id,
        "retried_by_status": item.retried_by_status,
        "retried_by_finished_at": _fmt_datetime(item.retried_by_finished_at),
        "retried_by_message": item.retried_by_message,
        "started_at": _fmt_datetime(item.started_at),
        "finished_at": _fmt_datetime(item.finished_at),
        "pages_fetched": item.pages_fetched,
        "documents_saved": item.documents_saved,
        "notices_upserted": item.notices_upserted,
        "deduplicated_count": item.deduplicated_count,
        "error_count": item.error_count,
        "list_items_seen": item.list_items_seen,
        "list_items_unique": item.list_items_unique,
        "list_items_source_duplicates_skipped": item.list_items_source_duplicates_skipped,
        "detail_pages_fetched": item.detail_pages_fetched,
        "records_inserted": item.records_inserted,
        "records_updated": item.records_updated,
        "source_duplicates_suppressed": item.source_duplicates_suppressed,
    }
    progress = build_crawl_job_progress(item)
    payload.update(
        {
            "is_active": bool(progress["is_active"]),
            "job_type_label": progress["job_type_label"],
            "status_label": progress["status_label"],
            "progress_stage_label": progress["stage_label"],
            "progress_summary": progress["summary_text"],
        }
    )
    return payload


def _load_job_banner(*, repository: CrawlJobRepository, job_id: int | None) -> dict[str, Any] | None:
    if job_id is None:
        return None
    item = repository.get_job_detail(job_id)
    if item is None:
        return None
    return _list_item_to_dict(item)


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _parse_message_key_values(message: str | None) -> dict[str, str]:
    if not message:
        return {}
    fields: dict[str, str] = {}
    for part in message.split(";"):
        chunk = part.strip()
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", maxsplit=1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        fields[normalized_key] = value.strip()
    return fields


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _enum_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _resolve_ops_filter(
    *,
    status: str | None,
    ops_filter: str | None,
) -> tuple[str | None, tuple[str, ...] | None, datetime | None]:
    if ops_filter == "abnormal":
        return status, ("failed", "partial"), None
    if ops_filter == "today_failed":
        today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        return "failed", None, today_start
    if ops_filter == "partial":
        return "partial", None, None
    return status, None, None
