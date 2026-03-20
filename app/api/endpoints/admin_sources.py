from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.endpoints.sources import (
    get_source_crawl_trigger_service,
    get_source_site_service,
)
from app.api.schemas import SourceCrawlJobTriggerRequest, SourceSitePatchRequest
from app.repositories import SourceSiteRepository
from app.services import SourceCrawlTriggerService, SourceSiteService

router = APIRouter(tags=["admin-sources"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

_BOOL_TRUE_SET = {"1", "true", "yes", "on"}
_BOOL_FALSE_SET = {"0", "false", "no", "off"}


def _parse_form_bool(value: str, *, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _BOOL_TRUE_SET:
        return True
    if normalized in _BOOL_FALSE_SET:
        return False
    raise HTTPException(status_code=400, detail=f"{field_name} must be boolean")


def _parse_form_positive_int(value: str, *, field_name: str) -> int:
    try:
        number = int(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be integer") from exc
    if number < 1:
        raise HTTPException(status_code=400, detail=f"{field_name} must be >= 1")
    return number


@router.get("/admin/sources", response_class=HTMLResponse)
def admin_sources_list(
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
) -> HTMLResponse:
    source_items = service.list_sources()
    context = {
        "request": request,
        "sources": [
            {
                "code": source.code,
                "name": source.name,
                "base_url": source.base_url,
                "is_active": source.is_active,
                "supports_js_render": source.supports_js_render,
                "crawl_interval_minutes": source.crawl_interval_minutes,
                "default_max_pages": source.default_max_pages,
            }
            for source in source_items
        ],
    }
    return TEMPLATES.TemplateResponse(name="admin/sources_list.html", context=context, request=request)


@router.get("/admin/sources/{code}", response_class=HTMLResponse)
def admin_source_detail(
    code: str,
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
) -> HTMLResponse:
    source = service.get_source(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    context = {
        "request": request,
        "source": source,
    }
    return TEMPLATES.TemplateResponse(name="admin/source_detail.html", context=context, request=request)


@router.post("/admin/sources/{code}/crawl-jobs")
async def admin_trigger_source_crawl_job(
    code: str,
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
) -> RedirectResponse:
    if service.get_source(code) is None:
        raise HTTPException(status_code=404, detail="source not found")

    source_model = SourceSiteRepository(trigger_service.session).get_model_by_code(code)
    if source_model is None:
        raise HTTPException(status_code=404, detail="source not found")

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)
    max_pages_raw = (form_data.get("max_pages") or ["1"])[0].strip()
    try:
        max_pages = int(max_pages_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="max_pages must be integer") from exc

    try:
        payload = SourceCrawlJobTriggerRequest(max_pages=max_pages, triggered_by="admin")
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc.errors()}") from exc
    result = trigger_service.trigger_manual_crawl(
        source=source_model,
        max_pages=payload.max_pages,
        triggered_by=payload.triggered_by,
    )

    return RedirectResponse(url=f"/admin/crawl-jobs/{result.job.id}", status_code=303)


@router.post("/admin/sources/{code}/config")
async def admin_update_source_config(
    code: str,
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
) -> RedirectResponse:
    if service.get_source(code) is None:
        raise HTTPException(status_code=404, detail="source not found")

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)

    is_active_raw = (form_data.get("is_active") or [""])[0]
    supports_js_render_raw = (form_data.get("supports_js_render") or [""])[0]
    crawl_interval_raw = (form_data.get("crawl_interval_minutes") or [""])[0]
    default_max_pages_raw = (form_data.get("default_max_pages") or [""])[0]

    payload_data = {
        "is_active": _parse_form_bool(is_active_raw, field_name="is_active"),
        "supports_js_render": _parse_form_bool(supports_js_render_raw, field_name="supports_js_render"),
        "crawl_interval_minutes": _parse_form_positive_int(crawl_interval_raw, field_name="crawl_interval_minutes"),
        "default_max_pages": _parse_form_positive_int(default_max_pages_raw, field_name="default_max_pages"),
    }
    try:
        payload = SourceSitePatchRequest(**payload_data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc.errors()}") from exc

    updated = service.update_source(code, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="source not found")

    return RedirectResponse(url=f"/admin/sources/{updated.code}", status_code=303)
