from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.endpoints.raw_documents import get_raw_document_detail, list_raw_documents
from app.db.session import get_db

router = APIRouter(tags=["admin-raw-documents"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


@router.get("/admin/raw-documents", response_class=HTMLResponse)
def admin_raw_documents_list(
    request: Request,
    source_code: str | None = Query(default=None),
    document_type: str | None = Query(default=None),
    crawl_job_id: int | None = Query(default=None, ge=1),
    content_hash: str | None = Query(default=None),
    from_notice_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = list_raw_documents(
        source_code=source_code,
        document_type=document_type,
        crawl_job_id=crawl_job_id,
        content_hash=content_hash,
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
        "document_type": document_type,
        "crawl_job_id": crawl_job_id,
        "content_hash": content_hash,
        "from_notice_id": from_notice_id,
        "limit": limit,
    }

    prev_url = _admin_list_url(common_query, prev_offset) if has_prev else None
    next_url = _admin_list_url(common_query, next_offset) if has_next else None

    context = {
        "request": request,
        "documents": [_list_item_to_dict(item) for item in payload.items],
        "source_code": source_code or "",
        "document_type": document_type or "",
        "crawl_job_id": crawl_job_id or "",
        "content_hash": content_hash or "",
        "from_notice_id": from_notice_id,
        "limit": limit,
        "offset": offset,
        "total": total,
        "prev_url": prev_url,
        "next_url": next_url,
        "document_type_options": ["html", "pdf", "json", "other"],
    }
    return TEMPLATES.TemplateResponse(name="admin/raw_documents_list.html", context=context, request=request)


@router.get("/admin/raw-documents/{raw_document_id}", response_class=HTMLResponse)
def admin_raw_document_detail(
    raw_document_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    payload = get_raw_document_detail(raw_document_id=raw_document_id, db=db)
    local_file_path = _resolve_local_file_path(payload.storage_uri)

    context = {
        "request": request,
        "raw_document": {
            "id": payload.id,
            "source_code": payload.source_code,
            "crawl_job_id": payload.crawl_job_id,
            "url": payload.url,
            "normalized_url": payload.normalized_url,
            "document_type": payload.document_type,
            "fetched_at": _fmt_datetime(payload.fetched_at),
            "storage_uri": payload.storage_uri,
            "mime_type": payload.mime_type,
            "title": payload.title,
            "content_hash": payload.content_hash,
        },
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
        "tender_notice": (
            {
                "id": payload.tender_notice.id,
                "source_code": payload.tender_notice.source_code,
                "title": payload.tender_notice.title,
                "notice_type": payload.tender_notice.notice_type,
                "published_at": _fmt_datetime(payload.tender_notice.published_at),
                "current_version_id": payload.tender_notice.current_version_id,
            }
            if payload.tender_notice is not None
            else None
        ),
        "download_url": f"/admin/raw-documents/{payload.id}/download" if local_file_path is not None else None,
        "raw_json": json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
    }
    return TEMPLATES.TemplateResponse(
        name="admin/raw_documents_detail.html",
        context=context,
        request=request,
    )


@router.get("/admin/raw-documents/{raw_document_id}/download")
def admin_raw_document_download(raw_document_id: int, db: Session = Depends(get_db)) -> FileResponse:
    payload = get_raw_document_detail(raw_document_id=raw_document_id, db=db)
    file_path = _resolve_local_file_path(payload.storage_uri)
    if file_path is None:
        raise HTTPException(status_code=404, detail="raw_document file not found")

    return FileResponse(
        path=str(file_path),
        media_type=payload.mime_type or "application/octet-stream",
        filename=file_path.name,
    )


def _resolve_local_file_path(storage_uri: str) -> Path | None:
    parsed = urlparse(storage_uri)
    if parsed.scheme != "file":
        return None
    if parsed.netloc not in ("", "localhost"):
        return None

    resolved = Path(unquote(parsed.path))
    if not resolved.is_file():
        return None
    return resolved


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _admin_list_url(common_query: dict[str, Any], offset: int) -> str:
    params = dict(common_query)
    params["offset"] = offset
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"/admin/raw-documents?{urlencode(clean)}"


def _list_item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_code": item.source_code,
        "crawl_job_id": item.crawl_job_id,
        "url": item.url,
        "normalized_url": item.normalized_url,
        "document_type": item.document_type,
        "fetched_at": _fmt_datetime(item.fetched_at),
        "storage_uri": item.storage_uri,
        "mime_type": item.mime_type,
        "title": item.title,
        "content_hash": item.content_hash,
    }
