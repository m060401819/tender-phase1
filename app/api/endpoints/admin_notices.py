from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.endpoints.notices import get_notice_detail, list_notices
from app.api.endpoints.stats import get_stats_overview
from app.api.schemas import NoticeType
from app.db.session import get_db
from app.repositories import NoticeRepository
from app.services import NoticeQueryService

router = APIRouter(tags=["admin-notices"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


@router.get("/admin/notices", response_class=HTMLResponse)
def admin_notices_list(
    request: Request,
    keyword: str | None = Query(default=None),
    source_code: str | None = Query(default=None),
    notice_type: NoticeType | None = Query(default=None),
    region: str | None = Query(default=None),
    recent_hours: int | None = Query(default=None, ge=1, le=720),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    dedup: bool = Query(default=True),
    sort_by: str = Query(default="published_at"),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    stats_payload = get_stats_overview(db=db)
    service = NoticeQueryService(repository=NoticeRepository(db))
    payload = list_notices(
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
        db=db,
    )
    raw_total = service.list_notices(
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=False,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=1,
        offset=0,
    ).total
    dedup_total = service.list_notices(
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=True,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=1,
        offset=0,
    ).total

    total = payload.total
    has_prev = offset > 0
    has_next = offset + limit < total

    prev_offset = max(offset - limit, 0)
    next_offset = offset + limit

    common_query: dict[str, Any] = {
        "keyword": keyword,
        "source_code": source_code,
        "notice_type": notice_type.value if notice_type else None,
        "region": region,
        "recent_hours": recent_hours,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "dedup": None if dedup else "false",
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
    }

    prev_url = _admin_list_url(common_query, prev_offset) if has_prev else None
    next_url = _admin_list_url(common_query, next_offset) if has_next else None
    export_csv_url = _notice_export_url(
        ext="csv",
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    export_json_url = _notice_export_url(
        ext="json",
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    export_xlsx_url = _notice_export_url(
        ext="xlsx",
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    notices = [
        {
            **_list_item_to_dict(item),
            "is_recent_new": bool(item.is_recent_new),
        }
        for item in payload.items
    ]
    recent_toggle_on_url = _admin_list_url(
        {
            **common_query,
            "recent_hours": 24,
        },
        0,
    )
    recent_toggle_off_url = _admin_list_url(
        {
            **common_query,
            "recent_hours": None,
        },
        0,
    )

    context = {
        "request": request,
        "notices": notices,
        "keyword": keyword or "",
        "source_code": source_code or "",
        "notice_type": notice_type.value if notice_type else "",
        "region": region or "",
        "recent_hours": recent_hours,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "dedup": dedup,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
        "offset": offset,
        "total": total,
        "prev_url": prev_url,
        "next_url": next_url,
        "export_csv_url": export_csv_url,
        "export_json_url": export_json_url,
        "export_xlsx_url": export_xlsx_url,
        "recent_toggle_on_url": recent_toggle_on_url,
        "recent_toggle_off_url": recent_toggle_off_url,
        "is_recent_24h_mode": recent_hours == 24,
        "is_dedup_mode": dedup,
        "raw_total_count": raw_total,
        "dedup_total_count": dedup_total,
        "today_new_notice_count": stats_payload.today_new_notice_count,
        "recent_24h_new_notice_count": stats_payload.recent_24h_new_notice_count,
        "notice_type_options": ["announcement", "change", "result"],
    }
    return TEMPLATES.TemplateResponse(name="admin/notices_list.html", context=context, request=request)


@router.get("/admin/notices/{notice_id}", response_class=HTMLResponse)
def admin_notice_detail(
    notice_id: int,
    request: Request,
    version_id: int | None = Query(default=None, ge=1),
    version_no: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_notice_detail(notice_id=notice_id, db=db)

    notice_dict = {
        "id": payload.id,
        "source_site_id": payload.source_site_id,
        "source_code": payload.source_code,
        "external_id": payload.external_id,
        "project_code": payload.project_code,
        "title": payload.title,
        "notice_type": payload.notice_type,
        "issuer": payload.issuer,
        "region": payload.region,
        "published_at": _fmt_datetime(payload.published_at),
        "deadline_at": _fmt_datetime(payload.deadline_at),
        "budget_amount": _fmt_decimal(payload.budget_amount),
        "budget_currency": payload.budget_currency,
        "summary": payload.summary,
        "first_published_at": _fmt_datetime(payload.first_published_at),
        "latest_published_at": _fmt_datetime(payload.latest_published_at),
        "current_version_id": payload.current_version_id,
    }

    source_dict = {
        "id": payload.source.id,
        "code": payload.source.code,
        "name": payload.source.name,
        "base_url": payload.source.base_url,
        "is_active": payload.source.is_active,
        "supports_js_render": payload.source.supports_js_render,
        "crawl_interval_minutes": payload.source.crawl_interval_minutes,
    }

    current_version_dict = None
    if payload.current_version is not None:
        current_version_dict = {
            "id": payload.current_version.id,
            "notice_id": payload.current_version.notice_id,
            "raw_document_id": payload.current_version.raw_document_id,
            "version_no": payload.current_version.version_no,
            "is_current": payload.current_version.is_current,
            "content_hash": payload.current_version.content_hash,
            "title": payload.current_version.title,
            "notice_type": payload.current_version.notice_type,
            "issuer": payload.current_version.issuer,
            "region": payload.current_version.region,
            "published_at": _fmt_datetime(payload.current_version.published_at),
            "deadline_at": _fmt_datetime(payload.current_version.deadline_at),
            "budget_amount": _fmt_decimal(payload.current_version.budget_amount),
            "budget_currency": payload.current_version.budget_currency,
            "change_summary": payload.current_version.change_summary,
        }

    versions = [
        {
            "id": item.id,
            "version_no": item.version_no,
            "is_current": item.is_current,
            "title": item.title,
            "notice_type": item.notice_type,
            "issuer": item.issuer,
            "region": item.region,
            "published_at": _fmt_datetime(item.published_at),
            "deadline_at": _fmt_datetime(item.deadline_at),
            "content_hash": item.content_hash,
            "raw_document_id": item.raw_document_id,
            "raw_document": (
                {
                    "id": item.raw_document.id,
                    "document_type": item.raw_document.document_type,
                    "fetched_at": _fmt_datetime(item.raw_document.fetched_at),
                    "storage_uri": item.raw_document.storage_uri,
                }
                if item.raw_document is not None
                else None
            ),
        }
        for item in payload.versions
    ]
    selected_version = _select_version(
        versions,
        version_id=version_id,
        version_no=version_no,
        current_version_id=payload.current_version_id,
    )
    selected_version_id = int(selected_version["id"]) if selected_version is not None else None
    selected_version_no = int(selected_version["version_no"]) if selected_version is not None else None

    version_no_map: dict[int, int] = {}
    for item in versions:
        item_id = _as_int(item.get("id"))
        item_version_no = _as_int(item.get("version_no"))
        if item_id is None or item_version_no is None:
            continue
        version_no_map[item_id] = item_version_no

    all_attachments = [
        {
            "id": item.id,
            "notice_version_id": item.notice_version_id,
            "notice_version_no": (
                version_no_map.get(int(item.notice_version_id))
                if item.notice_version_id is not None
                else None
            ),
            "file_name": item.file_name,
            "file_url": item.file_url,
            "attachment_type": item.attachment_type,
            "mime_type": item.mime_type,
            "file_size_bytes": item.file_size_bytes,
            "storage_uri": item.storage_uri,
        }
        for item in payload.attachments
    ]
    attachments = (
        [
            item
            for item in all_attachments
            if item["notice_version_id"] is not None and int(item["notice_version_id"]) == selected_version_id
        ]
        if selected_version_id is not None
        else all_attachments
    )

    raw_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2)
    related_items = NoticeQueryService(repository=NoticeRepository(db)).list_related_notices(notice_id)
    related_notices = [
        {
            "id": item.id,
            "source_code": item.source_code,
            "source_name": item.source_name,
            "title": item.title,
            "published_at": _fmt_datetime(item.published_at),
            "detail_url": item.detail_url,
        }
        for item in related_items
    ]

    context = {
        "request": request,
        "notice": notice_dict,
        "source": source_dict,
        "current_version": current_version_dict,
        "selected_version": selected_version,
        "selected_version_id": selected_version_id,
        "selected_version_no": selected_version_no,
        "versions": versions,
        "attachments": attachments,
        "all_attachments_count": len(all_attachments),
        "related_notices": related_notices,
        "related_notice_count": len(related_notices),
        "raw_json": raw_json,
    }
    return TEMPLATES.TemplateResponse(name="admin/notices_detail.html", context=context, request=request)


def _admin_list_url(common_query: dict[str, Any], offset: int) -> str:
    params = dict(common_query)
    params["offset"] = offset
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"/admin/notices?{urlencode(clean)}"


def _notice_export_url(
    *,
    ext: str,
    keyword: str | None,
    source_code: str | None,
    notice_type: str | None,
    region: str | None,
    recent_hours: int | None,
    date_from: str | None,
    date_to: str | None,
    dedup: bool,
    sort_by: str,
    sort_order: str,
) -> str:
    params = {
        "keyword": keyword,
        "source_code": source_code,
        "notice_type": notice_type,
        "region": region,
        "recent_hours": recent_hours,
        "date_from": date_from,
        "date_to": date_to,
        "dedup": None if dedup else "false",
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    query = urlencode(clean)
    if query:
        return f"/notices/export.{ext}?{query}"
    return f"/notices/export.{ext}"


def _list_item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_code": item.source_code,
        "source_name": item.source_name,
        "title": item.title,
        "notice_type": item.notice_type,
        "issuer": item.issuer,
        "region": item.region,
        "published_at": _fmt_datetime(item.published_at),
        "deadline_at": _fmt_datetime(item.deadline_at),
        "budget_amount": _fmt_decimal(item.budget_amount),
        "duplicate_count": int(item.duplicate_count),
    }


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _fmt_decimal(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return format(value, "f")


def _select_version(
    versions: list[dict[str, Any]],
    *,
    version_id: int | None,
    version_no: int | None,
    current_version_id: int | None,
) -> dict[str, Any] | None:
    if not versions:
        return None

    if version_id is not None:
        for item in versions:
            item_id = _as_int(item.get("id"))
            if item_id == version_id:
                return item

    if version_no is not None:
        for item in versions:
            item_version_no = _as_int(item.get("version_no"))
            if item_version_no == version_no:
                return item

    if current_version_id is not None:
        for item in versions:
            item_id = _as_int(item.get("id"))
            if item_id == current_version_id:
                return item

    return versions[0]


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None
