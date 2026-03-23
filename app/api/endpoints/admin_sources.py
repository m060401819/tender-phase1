from __future__ import annotations
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.endpoints.stats import get_stats_overview
from app.api.endpoints.sources import (
    get_source_crawl_trigger_service,
    get_source_site_service,
)
from app.api.schemas import (
    SourceCrawlJobTriggerRequest,
    SourceSiteAdminActiveCrawl,
    SourceSiteAdminRow,
    SourceSiteAdminRowActions,
    SourceSiteCreateRequest,
    SourceSitePatchRequest,
    SourceSitesAdminPageViewModel,
)
from app.core.auth import (
    AuthenticatedUser,
    UserRole,
    get_current_user,
    has_required_role,
    render_admin_template,
    require_admin_csrf,
    require_admin_user,
)
from app.db.session import get_db
from app.models import CrawlJob, SourceSite
from app.repositories import SourceSiteRepository
from app.services import (
    SourceActiveCrawlJobConflictError,
    SourceCrawlEnqueueResult,
    SourceCrawlTriggerService,
    SourceHealthService,
    SourceOpsService,
    SourceSiteService,
    get_source_adapter,
    list_integrated_source_codes,
    supports_job_type,
    sync_source_schedule,
)
from app.services.crawl_job_payloads import read_payload_int
from app.services.crawl_job_progress_service import ACTIVE_CRAWL_JOB_STATUSES, build_crawl_job_progress
from app.services.crawl_job_service import reconcile_expired_jobs_in_session

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


@router.get("/admin/sources", response_class=HTMLResponse, dependencies=[Depends(require_admin_user)])
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
                "official_url": source.official_url,
                "list_url": source.list_url,
                "is_active": source.is_active,
                "supports_js_render": source.supports_js_render,
                "crawl_interval_minutes": source.crawl_interval_minutes,
                "default_max_pages": source.default_max_pages,
            }
            for source in source_items
        ],
    }
    return TEMPLATES.TemplateResponse(name="admin/sources_list.html", context=context, request=request)


@router.get("/admin/source-sites", response_class=HTMLResponse)
def admin_product_source_sites_list(
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> HTMLResponse:
    stats_payload = get_stats_overview(db=db)
    source_items = service.list_sources()
    health_service = SourceHealthService(session=db)
    health_input_pairs: list[tuple[int, str]] = []
    for source in source_items:
        source_id = _as_int(getattr(source, "id", None))
        source_code = _as_non_empty_text(getattr(source, "code", None), default="")
        if source_id is None or not source_code:
            continue
        health_input_pairs.append((source_id, source_code))
    health_map = health_service.build_health_map(health_input_pairs)
    ops_map = {
        item.source_code: item
        for item in SourceOpsService(session=db).list_source_ops(recent_hours=24)
    }
    active_crawl_map = _load_active_crawl_map(
        session=db,
        source_codes=[
            _as_non_empty_text(getattr(source, "code", None), default="")
            for source in source_items
        ],
    )
    source_rows = [
        _normalize_source_sites_list_row(
            _build_source_sites_list_row(
                source=source,
                health=health_map.get(_as_int(getattr(source, "id", None)) or -1),
                ops=ops_map.get(_as_non_empty_text(getattr(source, "code", None), default="")),
                active_crawl=active_crawl_map.get(_as_non_empty_text(getattr(source, "code", None), default="")),
            ),
            source=source,
        )
        for source in source_items
    ]

    page = SourceSitesAdminPageViewModel(
        today_new_notice_count=stats_payload.today_new_notice_count,
        recent_24h_new_notice_count=stats_payload.recent_24h_new_notice_count,
        show_new_notice_alert=stats_payload.recent_24h_new_notice_count > 0,
        sources=source_rows,
        source_ops_report_url="/reports/source-ops.xlsx?recent_hours=24",
        created_source_success=request.query_params.get("created") == "1",
        created_source_code=request.query_params.get("created_code") or "",
        manual_crawl_error=request.query_params.get("manual_crawl_error") or "",
        manual_crawl_error_source_code=request.query_params.get("source_code") or "",
        active_crawl_job_count=len(active_crawl_map),
        auto_refresh_interval_seconds=5,
        can_manage_sources=has_required_role(current_user.role, UserRole.admin),
    )
    context = {
        "page": page,
    }
    return render_admin_template(
        templates=TEMPLATES,
        request=request,
        name="admin/source_sites_list.html",
        context=context,
        current_user=current_user,
    )


@router.get("/admin/sources/new", response_class=HTMLResponse, dependencies=[Depends(require_admin_user)])
def admin_source_create_page(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> HTMLResponse:
    context = {
        "errors": [],
        "schedule_day_options": [1, 2, 3, 7],
        "form": _default_source_form_values(),
        "integrated_source_codes": list_integrated_source_codes(),
    }
    return render_admin_template(
        templates=TEMPLATES,
        request=request,
        name="admin/source_new.html",
        context=context,
        current_user=current_user,
    )


@router.post("/admin/sources/new", dependencies=[Depends(require_admin_user)])
async def admin_source_create_submit(
    request: Request,
    db: Session = Depends(get_db),
    service: SourceSiteService = Depends(get_source_site_service),
    current_user: AuthenticatedUser = Depends(get_current_user),
    _csrf_protected: None = Depends(require_admin_csrf),
):
    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)
    form_values = _source_form_values_from_request(form_data)
    errors: list[str] = []

    is_active = _safe_parse_form_bool(form_values["is_active"], field_name="is_active", errors=errors)
    schedule_enabled = _safe_parse_form_bool(
        form_values["schedule_enabled"],
        field_name="schedule_enabled",
        errors=errors,
    )
    schedule_days = _safe_parse_schedule_days(form_values["schedule_days"], errors=errors)
    crawl_interval_minutes = _safe_parse_form_positive_int(
        form_values["crawl_interval_minutes"],
        field_name="crawl_interval_minutes",
        errors=errors,
    )
    default_max_pages = _safe_parse_optional_positive_int(
        form_values["default_max_pages"],
        field_name="default_max_pages",
        errors=errors,
    )

    payload: SourceSiteCreateRequest | None = None
    if (
        not errors
        and is_active is not None
        and schedule_enabled is not None
        and schedule_days is not None
        and crawl_interval_minutes is not None
    ):
        try:
            payload = SourceSiteCreateRequest.model_validate(
                {
                    "source_code": form_values["source_code"],
                    "source_name": form_values["source_name"],
                    "official_url": form_values["official_url"],
                    "list_url": form_values["list_url"],
                    "remark": form_values["remark"] or None,
                    "is_active": is_active,
                    "schedule_enabled": schedule_enabled,
                    "schedule_days": schedule_days,
                    "crawl_interval_minutes": crawl_interval_minutes,
                    "default_max_pages": default_max_pages,
                }
            )
        except ValidationError as exc:
            errors.extend(_humanize_validation_errors(exc))

    if payload is not None and not errors:
        try:
            created = service.create_source(
                source_code=payload.source_code,
                source_name=payload.source_name,
                official_url=str(payload.official_url),
                list_url=str(payload.list_url),
                remark=payload.remark,
                is_active=payload.is_active,
                schedule_enabled=payload.schedule_enabled,
                schedule_days=payload.schedule_days,
                crawl_interval_minutes=payload.crawl_interval_minutes,
                default_max_pages=payload.default_max_pages,
            )
            sync_source_schedule(created.code, fallback_session=db)
            return RedirectResponse(
                url=f"/admin/source-sites?created=1&created_code={created.code}",
                status_code=303,
            )
        except ValueError as exc:
            errors.append(str(exc))

    context = {
        "errors": errors,
        "schedule_day_options": [1, 2, 3, 7],
        "form": form_values,
        "integrated_source_codes": list_integrated_source_codes(),
    }
    return render_admin_template(
        templates=TEMPLATES,
        request=request,
        name="admin/source_new.html",
        context=context,
        current_user=current_user,
        status_code=400,
    )


@router.get("/admin/sources/{code}", response_class=HTMLResponse, dependencies=[Depends(require_admin_user)])
def admin_source_detail(
    code: str,
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> HTMLResponse:
    source = service.get_source(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    adapter = get_source_adapter(source.code)
    health_summary = SourceHealthService(session=db).get_source_health_by_code(source.code)
    if health_summary is None:
        raise HTTPException(status_code=404, detail="source not found")
    ops_summary = SourceOpsService(session=db).get_source_ops(source_code=source.code, recent_hours=24)
    active_crawl = _load_active_crawl_map(session=db, source_codes=[source.code]).get(source.code)

    context = {
        "source": source,
        "business_code": adapter.business_code if adapter is not None else source.code,
        "crawl_supported": adapter is not None,
        "supported_job_types_label": " / ".join(adapter.supported_job_types) if adapter is not None else "-",
        "supports_backfill": adapter is not None and ("backfill" in adapter.supported_job_types),
        "crawl_support_message": "" if adapter is not None else "仅保存来源信息，尚未接入抓取逻辑",
        "schedule_updated": request.query_params.get("schedule_updated") == "1",
        "schedule_day_options": [1, 2, 3, 7],
        "schedule_days_label": _schedule_days_label(source.schedule_days),
        "health_summary": {
            "health_status": health_summary.health_status,
            "health_status_label": health_summary.health_status_label,
            "latest_job_id": health_summary.latest_job_id,
            "latest_job_status": health_summary.latest_job_status,
            "latest_job_status_label": health_summary.latest_job_status_label,
            "latest_job_started_at": _fmt_datetime(health_summary.latest_job_started_at),
            "latest_notices_upserted": health_summary.latest_notices_upserted,
            "latest_error_count": health_summary.latest_error_count,
            "latest_list_items_seen": health_summary.latest_list_items_seen,
            "latest_list_items_unique": health_summary.latest_list_items_unique,
            "latest_list_items_source_duplicates_skipped": health_summary.latest_list_items_source_duplicates_skipped,
            "latest_detail_pages_fetched": health_summary.latest_detail_pages_fetched,
            "latest_source_duplicates_suppressed": health_summary.latest_source_duplicates_suppressed,
            "recent_7d_job_count": health_summary.recent_7d_job_count,
            "recent_7d_failed_count": health_summary.recent_7d_failed_count,
            "recent_7d_error_count": health_summary.recent_7d_error_count,
            "latest_failure_reason": health_summary.latest_failure_reason,
        },
        "ops_summary": (
            {
                "today_crawl_job_count": ops_summary.today_crawl_job_count,
                "today_success_count": ops_summary.today_success_count,
                "today_failed_count": ops_summary.today_failed_count,
                "today_partial_count": ops_summary.today_partial_count,
                "today_new_notice_count": ops_summary.today_new_notice_count,
                "last_error_message": ops_summary.last_error_message or "-",
                "last_retry_status": ops_summary.last_retry_status or "-",
                "last_retry_job_id": ops_summary.last_retry_job_id,
                "last_job_status": ops_summary.last_job_status or "-",
                "last_job_finished_at": _fmt_datetime(ops_summary.last_job_finished_at),
            }
            if ops_summary is not None
            else {
                "today_crawl_job_count": 0,
                "today_success_count": 0,
                "today_failed_count": 0,
                "today_partial_count": 0,
                "today_new_notice_count": 0,
                "last_error_message": "-",
                "last_retry_status": "-",
                "last_retry_job_id": None,
                "last_job_status": "-",
                "last_job_finished_at": "-",
            }
        ),
        "manual_crawl_error": request.query_params.get("manual_crawl_error") or "",
        "has_active_crawl": active_crawl is not None,
        "active_crawl": active_crawl or {},
    }
    return render_admin_template(
        templates=TEMPLATES,
        request=request,
        name="admin/source_detail.html",
        context=context,
        current_user=current_user,
    )


@router.post("/admin/sources/{code}/manual-crawl", name="admin_manual_crawl_source")
async def admin_trigger_source_manual_crawl(
    code: str,
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
    _csrf_protected: None = Depends(require_admin_csrf),
) -> RedirectResponse:
    source_record = service.get_source(code)
    if source_record is None:
        raise HTTPException(status_code=404, detail="source not found")

    source_model = SourceSiteRepository(trigger_service.session).get_model_by_code(source_record.code)
    if source_model is None:
        raise HTTPException(status_code=404, detail="source not found")

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)
    return_to = (form_data.get("return_to") or [""])[0].strip().lower()

    if not source_model.is_active:
        return RedirectResponse(
            url=_manual_crawl_error_redirect_url(
                source_code=source_model.code,
                message="来源未启用，无法手动抓取",
                return_to=return_to,
            ),
            status_code=303,
        )

    adapter = get_source_adapter(source_model.code)
    if adapter is None:
        return RedirectResponse(
            url=_manual_crawl_error_redirect_url(
                source_code=source_model.code,
                message="仅保存来源信息，尚未接入抓取逻辑",
                return_to=return_to,
            ),
            status_code=303,
        )
    if not supports_job_type(source_model.code, job_type="manual"):
        return RedirectResponse(
            url=_manual_crawl_error_redirect_url(
                source_code=source_model.code,
                message="当前来源不支持手动抓取",
                return_to=return_to,
            ),
            status_code=303,
        )

    try:
        default_max_pages = int(source_model.default_max_pages or 50)
    except (TypeError, ValueError):
        return RedirectResponse(
            url=_manual_crawl_error_redirect_url(
                source_code=source_model.code,
                message="来源默认抓取页数配置无效，无法手动抓取",
                return_to=return_to,
            ),
            status_code=303,
        )

    try:
        result = trigger_service.queue_manual_crawl(
            source=source_model,
            max_pages=default_max_pages,
            triggered_by="admin_ui",
        )
    except Exception as exc:
        return RedirectResponse(
            url=_manual_crawl_error_redirect_url(
                source_code=source_model.code,
                message=_manual_crawl_create_error_message(exc),
                return_to=return_to,
            ),
            status_code=303,
        )
    return RedirectResponse(
        url=_manual_crawl_success_redirect_url(
            source_code=source_model.code,
            created_job_id=result.job.id,
        ),
        status_code=303,
    )


@router.post("/admin/sources/{code}/crawl-jobs")
async def admin_trigger_source_crawl_job(
    code: str,
    request: Request,
    service: SourceSiteService = Depends(get_source_site_service),
    trigger_service: SourceCrawlTriggerService = Depends(get_source_crawl_trigger_service),
    _csrf_protected: None = Depends(require_admin_csrf),
) -> RedirectResponse:
    source_record = service.get_source(code)
    if source_record is None:
        raise HTTPException(status_code=404, detail="source not found")

    source_model = SourceSiteRepository(trigger_service.session).get_model_by_code(source_record.code)
    if source_model is None:
        raise HTTPException(status_code=404, detail="source not found")
    adapter = get_source_adapter(source_model.code)
    if adapter is None:
        raise HTTPException(status_code=400, detail="仅保存来源信息，尚未接入抓取逻辑")

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)
    action = (form_data.get("action") or ["trigger"])[0].strip() or "trigger"

    if action == "retry_latest":
        try:
            result = _trigger_latest_retry_for_source(
                source=source_model,
                trigger_service=trigger_service,
            )
        except SourceActiveCrawlJobConflictError as exc:
            return RedirectResponse(
                url=_manual_crawl_error_redirect_url(
                    source_code=source_model.code,
                    message=str(exc),
                    return_to="detail",
                ),
                status_code=303,
            )
        return RedirectResponse(url=f"/admin/crawl-jobs/{result.job.id}", status_code=303)

    max_pages_raw = (form_data.get("max_pages") or [""])[0].strip()
    max_pages = None
    if max_pages_raw:
        try:
            max_pages = int(max_pages_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="max_pages must be integer") from exc

    job_type_raw = (form_data.get("job_type") or ["manual"])[0].strip() or "manual"
    backfill_year_raw = (form_data.get("backfill_year") or [""])[0].strip()
    backfill_year = None
    if backfill_year_raw:
        try:
            backfill_year = int(backfill_year_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="backfill_year must be integer") from exc

    try:
        payload = SourceCrawlJobTriggerRequest.model_validate(
            {
                "max_pages": max_pages,
                "triggered_by": "admin",
                "job_type": job_type_raw,
                "backfill_year": backfill_year,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc.errors()}") from exc

    if payload.job_type not in adapter.supported_job_types:
        supported = " / ".join(adapter.supported_job_types)
        raise HTTPException(
            status_code=400,
            detail=f"source={source_model.code} 不支持 job_type={payload.job_type}，支持模式: {supported}",
        )

    effective_max_pages = payload.max_pages if payload.max_pages is not None else int(source_model.default_max_pages)
    try:
        if payload.job_type == "backfill":
            if payload.backfill_year is None:
                raise HTTPException(status_code=400, detail="backfill_year is required for backfill job")
            result = trigger_service.queue_backfill_crawl(
                source=source_model,
                backfill_year=payload.backfill_year,
                max_pages=effective_max_pages,
                triggered_by=payload.triggered_by,
            )
        else:
            result = trigger_service.queue_manual_crawl(
                source=source_model,
                max_pages=effective_max_pages,
                triggered_by=payload.triggered_by,
            )
    except SourceActiveCrawlJobConflictError as exc:
        return RedirectResponse(
            url=_manual_crawl_error_redirect_url(
                source_code=source_model.code,
                message=str(exc),
                return_to="detail",
            ),
            status_code=303,
        )

    return RedirectResponse(url=f"/admin/crawl-jobs/{result.job.id}", status_code=303)


def _trigger_latest_retry_for_source(
    *,
    source: SourceSite,
    trigger_service: SourceCrawlTriggerService,
) -> SourceCrawlEnqueueResult:
    session = trigger_service.session
    candidate_jobs = session.scalars(
        select(CrawlJob)
        .where(
            CrawlJob.source_site_id == source.id,
            CrawlJob.status.in_(["failed", "partial"]),
        )
        .order_by(CrawlJob.id.desc())
        .limit(30)
    ).all()

    latest_retryable: CrawlJob | None = None
    for candidate in candidate_jobs:
        if candidate.retry_of_job_id is not None:
            continue
        already_retried = session.scalar(select(CrawlJob.id).where(CrawlJob.retry_of_job_id == candidate.id))
        if already_retried is not None:
            continue
        latest_retryable = candidate
        break

    if latest_retryable is not None and latest_retryable.job_type == "manual":
        inherited_max_pages = read_payload_int(latest_retryable.job_params_json, "max_pages") or int(
            source.default_max_pages
        )
        inherited_backfill_year = read_payload_int(latest_retryable.job_params_json, "backfill_year")
        return trigger_service.queue_retry_crawl(
            source=source,
            retry_of_job_id=int(latest_retryable.id),
            max_pages=inherited_max_pages,
            backfill_year=inherited_backfill_year,
            triggered_by="admin-retry",
        )

    return trigger_service.queue_manual_crawl(
        source=source,
        max_pages=int(source.default_max_pages),
        triggered_by="admin",
    )


@router.post("/admin/sources/{code}/config", dependencies=[Depends(require_admin_user)])
async def admin_update_source_config(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    service: SourceSiteService = Depends(get_source_site_service),
    _csrf_protected: None = Depends(require_admin_csrf),
) -> RedirectResponse:
    if service.get_source(code) is None:
        raise HTTPException(status_code=404, detail="source not found")

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)

    source_name_raw = (form_data.get("source_name") or [""])[0].strip()
    official_url_raw = (form_data.get("official_url") or [""])[0].strip()
    list_url_raw = (form_data.get("list_url") or [""])[0].strip()
    description_raw = (form_data.get("description") or [""])[0].strip()
    is_active_raw = (form_data.get("is_active") or [""])[0]
    supports_js_render_raw = (form_data.get("supports_js_render") or [""])[0]
    crawl_interval_raw = (form_data.get("crawl_interval_minutes") or [""])[0]
    default_max_pages_raw = (form_data.get("default_max_pages") or [""])[0]

    payload_data = {
        "name": source_name_raw or None,
        "official_url": official_url_raw or None,
        "list_url": list_url_raw or None,
        "description": description_raw or None,
        "is_active": _parse_form_bool(is_active_raw, field_name="is_active"),
        "supports_js_render": _parse_form_bool(supports_js_render_raw, field_name="supports_js_render"),
        "crawl_interval_minutes": _parse_form_positive_int(crawl_interval_raw, field_name="crawl_interval_minutes"),
        "default_max_pages": _parse_form_positive_int(default_max_pages_raw, field_name="default_max_pages"),
    }
    try:
        payload = SourceSitePatchRequest.model_validate(payload_data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc.errors()}") from exc

    updates = payload.model_dump(exclude_unset=True)
    if "official_url" in updates:
        updates["official_url"] = str(updates["official_url"])
        updates["base_url"] = updates["official_url"]
    if "list_url" in updates:
        updates["list_url"] = str(updates["list_url"])

    updated = service.update_source(code, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="source not found")
    sync_source_schedule(updated.code, fallback_session=db)

    return RedirectResponse(url=f"/admin/sources/{updated.code}", status_code=303)


@router.post("/admin/sources/{code}/schedule", dependencies=[Depends(require_admin_user)])
async def admin_update_source_schedule(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    service: SourceSiteService = Depends(get_source_site_service),
    _csrf_protected: None = Depends(require_admin_csrf),
) -> RedirectResponse:
    source = service.get_source(code)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)

    schedule_enabled_raw = (form_data.get("schedule_enabled") or [""])[0]
    schedule_days_raw = (form_data.get("schedule_days") or [""])[0]

    schedule_enabled = _parse_form_bool(schedule_enabled_raw, field_name="schedule_enabled")
    schedule_days = _parse_form_positive_int(schedule_days_raw, field_name="schedule_days")
    if schedule_days not in {1, 2, 3, 7}:
        raise HTTPException(status_code=400, detail="schedule_days must be one of 1,2,3,7")

    updated = service.update_source(
        code,
        {
            "schedule_enabled": schedule_enabled,
            "schedule_days": schedule_days,
        },
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="source not found")

    sync_source_schedule(updated.code, fallback_session=db)
    return RedirectResponse(url=f"/admin/sources/{updated.code}?schedule_updated=1", status_code=303)


def _crawl_interval_label(minutes: int) -> str:
    day_map = {
        1440: "1天一次",
        2880: "2天一次",
        4320: "3天一次",
        10080: "7天一次",
    }
    return day_map.get(int(minutes), f"{int(minutes)} 分钟")


def _schedule_days_label(days: int) -> str:
    day_map = {
        1: "1天一次",
        2: "2天一次",
        3: "3天一次",
        7: "7天一次",
    }
    return day_map.get(int(days), f"{int(days)} 天")


def _health_badge_by_status(status: str) -> str:
    return {
        "normal": "tag-health-normal",
        "warning": "tag-health-warning",
        "critical": "tag-health-critical",
    }.get(status, "tag-zero")


def _as_non_empty_text(value: object, *, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text


def _as_int_default(value: object, *, default: int = 0) -> int:
    parsed = _as_int(value)
    return parsed if parsed is not None else default


def _build_source_sites_list_row(
    *,
    source: object,
    health: object | None,
    ops: object | None,
    active_crawl: SourceSiteAdminActiveCrawl | dict[str, object] | None = None,
) -> SourceSiteAdminRow:
    source_id = _as_int(getattr(source, "id", None)) or 0
    raw_code = _as_non_empty_text(getattr(source, "code", None), default="")
    code = raw_code or "-"
    name = _as_non_empty_text(getattr(source, "name", None), default=code)
    base_url = _as_non_empty_text(getattr(source, "base_url", None), default="-")
    official_url = _as_non_empty_text(getattr(source, "official_url", None), default=base_url)
    list_url = _as_non_empty_text(getattr(source, "list_url", None), default=base_url)
    is_active = bool(getattr(source, "is_active", False))
    crawl_interval_minutes = _as_int_default(getattr(source, "crawl_interval_minutes", None), default=60)
    default_max_pages = _as_int_default(getattr(source, "default_max_pages", None), default=50)
    schedule_enabled = bool(getattr(source, "schedule_enabled", False))
    schedule_days = _as_int_default(getattr(source, "schedule_days", None), default=1)
    last_scheduled_run_at = _fmt_datetime(getattr(source, "last_scheduled_run_at", None))
    next_scheduled_run_at = _fmt_datetime(getattr(source, "next_scheduled_run_at", None))
    last_schedule_status = _as_non_empty_text(getattr(source, "last_schedule_status", None), default="-")
    description = _as_non_empty_text(getattr(source, "description", None), default="-")

    health_status = _as_non_empty_text(getattr(health, "health_status", None), default="warning")
    health_status_label = _as_non_empty_text(getattr(health, "health_status_label", None), default="警告")
    last_crawl_result = _as_non_empty_text(getattr(health, "latest_job_status_label", None), default="-")
    last_failure_summary = _as_non_empty_text(getattr(health, "latest_failure_reason", None), default="-")
    last_crawled_at = _fmt_datetime(getattr(health, "latest_job_started_at", None))
    last_new_notice_count = _as_int_default(getattr(health, "latest_notices_upserted", None), default=0)
    latest_list_items_seen = _as_int_default(getattr(health, "latest_list_items_seen", None), default=0)
    latest_list_items_unique = _as_int_default(getattr(health, "latest_list_items_unique", None), default=0)
    latest_list_items_source_duplicates_skipped = _as_int_default(
        getattr(health, "latest_list_items_source_duplicates_skipped", None),
        default=0,
    )
    latest_detail_pages_fetched = _as_int_default(getattr(health, "latest_detail_pages_fetched", None), default=0)
    latest_source_duplicates_suppressed = _as_int_default(
        getattr(health, "latest_source_duplicates_suppressed", None),
        default=0,
    )
    has_source_duplicates_latest = (
        latest_list_items_source_duplicates_skipped + latest_source_duplicates_suppressed
    ) > 0
    recent_7d_error_count = _as_int_default(getattr(health, "recent_7d_error_count", None), default=0)

    today_crawl_job_count = _as_int_default(getattr(ops, "today_crawl_job_count", None), default=0)
    today_success_count = _as_int_default(getattr(ops, "today_success_count", None), default=0)
    today_failed_count = _as_int_default(getattr(ops, "today_failed_count", None), default=0)
    today_new_notice_count = _as_int_default(getattr(ops, "today_new_notice_count", None), default=0)
    last_retry_status = _as_non_empty_text(getattr(ops, "last_retry_status", None), default="-")
    last_retry_job_id = _as_int(getattr(ops, "last_retry_job_id", None))
    last_retry_label = last_retry_status if last_retry_job_id is not None else "无"
    today_ops_summary = f"成功 {today_success_count} / 失败 {today_failed_count} / 新增 {today_new_notice_count}"

    adapter = get_source_adapter(raw_code) if raw_code else None
    supported_job_types = list(getattr(adapter, "supported_job_types", []) or [])
    supported_job_types_label = " / ".join(str(item) for item in supported_job_types) if supported_job_types else "-"
    crawl_supported = adapter is not None
    crawl_support_message = "" if crawl_supported else "仅保存来源信息，尚未接入抓取逻辑"
    business_code = _as_non_empty_text(
        getattr(adapter, "business_code", None),
        default=code,
    )

    active_crawl_view = _normalize_source_sites_active_crawl(active_crawl, code=raw_code or code)

    return SourceSiteAdminRow(
        id=source_id,
        code=code,
        name=name,
        base_url=base_url,
        official_url=official_url,
        list_url=list_url,
        is_active=is_active,
        crawl_interval_minutes=crawl_interval_minutes,
        crawl_interval_label=_crawl_interval_label(crawl_interval_minutes),
        last_crawled_at=last_crawled_at,
        last_new_notice_count=last_new_notice_count,
        last_new_count=last_new_notice_count,
        has_new_notice=last_new_notice_count > 0,
        health_status=health_status,
        health_badge=_health_badge_by_status(health_status),
        health_status_label=health_status_label,
        last_crawl_result=last_crawl_result,
        last_failure_summary=last_failure_summary,
        latest_job_status_label=last_crawl_result,
        latest_failure_reason=last_failure_summary,
        latest_list_items_seen=latest_list_items_seen,
        latest_list_items_unique=latest_list_items_unique,
        latest_list_items_source_duplicates_skipped=latest_list_items_source_duplicates_skipped,
        latest_detail_pages_fetched=latest_detail_pages_fetched,
        latest_source_duplicates_suppressed=latest_source_duplicates_suppressed,
        has_source_duplicates_latest=has_source_duplicates_latest,
        recent_7d_error_count=recent_7d_error_count,
        default_max_pages=default_max_pages,
        schedule_enabled=schedule_enabled,
        schedule_days=schedule_days,
        schedule_days_label=_schedule_days_label(schedule_days),
        description=description,
        last_scheduled_run_at=last_scheduled_run_at,
        next_scheduled_run_at=next_scheduled_run_at,
        last_schedule_status=last_schedule_status,
        today_crawl_job_count=today_crawl_job_count,
        today_success_count=today_success_count,
        today_failed_count=today_failed_count,
        today_new_notice_count=today_new_notice_count,
        today_ops_summary=today_ops_summary,
        last_retry_status=last_retry_status,
        last_retry_job_id=last_retry_job_id,
        last_retry_label=last_retry_label,
        business_code=business_code,
        crawl_supported=crawl_supported,
        supported_job_types_label=supported_job_types_label,
        supports_backfill="backfill" in supported_job_types,
        crawl_support_message=crawl_support_message,
        has_active_crawl=active_crawl_view.id is not None,
        active_crawl=active_crawl_view,
        actions=_default_source_sites_list_actions(raw_code or code),
    )


def _normalize_source_sites_list_row(
    row: object,
    *,
    source: object | None = None,
) -> SourceSiteAdminRow:
    if isinstance(row, SourceSiteAdminRow):
        return row
    row_dict = row.model_dump() if hasattr(row, "model_dump") else (dict(row) if isinstance(row, dict) else {})
    fallback_code = _as_non_empty_text(getattr(source, "code", None), default="-")
    code = _as_non_empty_text(row_dict.get("code"), default=fallback_code)
    base_url = _as_non_empty_text(
        row_dict.get("base_url"),
        default=_as_non_empty_text(getattr(source, "base_url", None), default="-"),
    )
    official_url = _as_non_empty_text(
        row_dict.get("official_url"),
        default=_as_non_empty_text(getattr(source, "official_url", None), default=base_url),
    )
    list_url = _as_non_empty_text(
        row_dict.get("list_url"),
        default=_as_non_empty_text(getattr(source, "list_url", None), default=base_url),
    )
    schedule_days = _as_int_default(
        row_dict.get("schedule_days"),
        default=_as_int(getattr(source, "schedule_days", None)) or 1,
    )
    today_success_count = _as_int_default(row_dict.get("today_success_count"), default=0)
    today_failed_count = _as_int_default(row_dict.get("today_failed_count"), default=0)
    today_new_notice_count = _as_int_default(row_dict.get("today_new_notice_count"), default=0)
    last_retry_job_id = _as_int(row_dict.get("last_retry_job_id"))
    last_retry_status = _as_non_empty_text(row_dict.get("last_retry_status"), default="-")
    last_new_notice_count = _as_int_default(row_dict.get("last_new_notice_count"), default=0)
    active_crawl = _normalize_source_sites_active_crawl(row_dict.get("active_crawl"), code=code)

    defaults: dict[str, object] = {
        "id": _as_int(getattr(source, "id", None)) or 0,
        "code": code,
        "name": _as_non_empty_text(
            row_dict.get("name"),
            default=_as_non_empty_text(getattr(source, "name", None), default=code),
        ),
        "base_url": base_url,
        "official_url": official_url,
        "list_url": list_url,
        "is_active": bool(row_dict.get("is_active", getattr(source, "is_active", False))),
        "crawl_interval_minutes": _as_int_default(
            row_dict.get("crawl_interval_minutes"),
            default=_as_int(getattr(source, "crawl_interval_minutes", None)) or 60,
        ),
        "crawl_interval_label": _as_non_empty_text(
            row_dict.get("crawl_interval_label"),
            default=_crawl_interval_label(
                _as_int_default(row_dict.get("crawl_interval_minutes"), default=_as_int(getattr(source, "crawl_interval_minutes", None)) or 60)
            ),
        ),
        "health_status": _as_non_empty_text(row_dict.get("health_status"), default="warning"),
        "health_badge": _as_non_empty_text(row_dict.get("health_badge"), default="tag-zero"),
        "health_status_label": _as_non_empty_text(row_dict.get("health_status_label"), default="警告"),
        "last_crawl_result": _as_non_empty_text(row_dict.get("last_crawl_result"), default="-"),
        "last_failure_summary": _as_non_empty_text(row_dict.get("last_failure_summary"), default="-"),
        "latest_job_status_label": _as_non_empty_text(
            row_dict.get("latest_job_status_label"),
            default=_as_non_empty_text(row_dict.get("last_crawl_result"), default="-"),
        ),
        "latest_failure_reason": _as_non_empty_text(
            row_dict.get("latest_failure_reason"),
            default=_as_non_empty_text(row_dict.get("last_failure_summary"), default="-"),
        ),
        "latest_list_items_seen": _as_int_default(row_dict.get("latest_list_items_seen"), default=0),
        "latest_list_items_unique": _as_int_default(row_dict.get("latest_list_items_unique"), default=0),
        "latest_list_items_source_duplicates_skipped": _as_int_default(
            row_dict.get("latest_list_items_source_duplicates_skipped"),
            default=0,
        ),
        "latest_detail_pages_fetched": _as_int_default(row_dict.get("latest_detail_pages_fetched"), default=0),
        "latest_source_duplicates_suppressed": _as_int_default(
            row_dict.get("latest_source_duplicates_suppressed"),
            default=0,
        ),
        "has_source_duplicates_latest": bool(row_dict.get("has_source_duplicates_latest", False)),
        "recent_7d_error_count": _as_int_default(row_dict.get("recent_7d_error_count"), default=0),
        "default_max_pages": _as_int_default(
            row_dict.get("default_max_pages"),
            default=_as_int(getattr(source, "default_max_pages", None)) or 50,
        ),
        "schedule_enabled": bool(row_dict.get("schedule_enabled", getattr(source, "schedule_enabled", False))),
        "schedule_days": schedule_days,
        "schedule_days_label": _as_non_empty_text(
            row_dict.get("schedule_days_label"),
            default=_schedule_days_label(schedule_days),
        ),
        "description": _as_non_empty_text(
            row_dict.get("description"),
            default=_as_non_empty_text(getattr(source, "description", None), default="-"),
        ),
        "last_scheduled_run_at": _as_non_empty_text(row_dict.get("last_scheduled_run_at"), default="-"),
        "next_scheduled_run_at": _as_non_empty_text(row_dict.get("next_scheduled_run_at"), default="-"),
        "last_schedule_status": _as_non_empty_text(row_dict.get("last_schedule_status"), default="-"),
        "last_crawled_at": _as_non_empty_text(row_dict.get("last_crawled_at"), default="-"),
        "last_new_notice_count": last_new_notice_count,
        "last_new_count": _as_int_default(row_dict.get("last_new_count"), default=last_new_notice_count),
        "has_new_notice": bool(row_dict.get("has_new_notice", last_new_notice_count > 0)),
        "today_crawl_job_count": _as_int_default(row_dict.get("today_crawl_job_count"), default=0),
        "today_success_count": today_success_count,
        "today_failed_count": today_failed_count,
        "today_new_notice_count": today_new_notice_count,
        "today_ops_summary": _as_non_empty_text(
            row_dict.get("today_ops_summary"),
            default=f"成功 {today_success_count} / 失败 {today_failed_count} / 新增 {today_new_notice_count}",
        ),
        "last_retry_status": last_retry_status,
        "last_retry_job_id": last_retry_job_id,
        "last_retry_label": _as_non_empty_text(
            row_dict.get("last_retry_label"),
            default=last_retry_status if last_retry_job_id is not None else "无",
        ),
        "business_code": _as_non_empty_text(row_dict.get("business_code"), default=code),
        "crawl_supported": bool(row_dict.get("crawl_supported", False)),
        "supported_job_types_label": _as_non_empty_text(row_dict.get("supported_job_types_label"), default="-"),
        "supports_backfill": bool(row_dict.get("supports_backfill", False)),
        "crawl_support_message": _as_non_empty_text(row_dict.get("crawl_support_message"), default=""),
        "has_active_crawl": bool(row_dict.get("has_active_crawl", active_crawl.id is not None)),
        "active_crawl": active_crawl,
        "actions": _normalize_source_sites_list_actions(row_dict.get("actions"), code=code),
    }
    merged = {
        **defaults,
        **{key: value for key, value in row_dict.items() if key not in defaults and value is not None},
    }
    merged["active_crawl"] = active_crawl
    merged["actions"] = _normalize_source_sites_list_actions(row_dict.get("actions"), code=code)
    return SourceSiteAdminRow.model_validate(merged)


def _default_source_sites_list_actions(code: str) -> SourceSiteAdminRowActions:
    normalized_code = code if code and code != "-" else ""
    return SourceSiteAdminRowActions(
        manual_crawl_post_url=(
            f"/admin/sources/{normalized_code}/manual-crawl" if normalized_code else "/admin/sources/manual-crawl"
        ),
        crawl_jobs_url=(
            f"/admin/crawl-jobs?source_code={normalized_code}" if normalized_code else "/admin/crawl-jobs"
        ),
        crawl_errors_url=(
            f"/admin/crawl-errors?source_code={normalized_code}" if normalized_code else "/admin/crawl-errors"
        ),
        config_url=f"/admin/sources/{normalized_code}" if normalized_code else "/admin/sources",
    )


def _normalize_source_sites_list_actions(
    value: object,
    *,
    code: str,
) -> SourceSiteAdminRowActions:
    if isinstance(value, SourceSiteAdminRowActions):
        return value
    default_actions = _default_source_sites_list_actions(code)
    actions_dict = value.model_dump() if hasattr(value, "model_dump") else (dict(value) if isinstance(value, dict) else {})
    return SourceSiteAdminRowActions(
        manual_crawl_post_url=_as_non_empty_text(
            actions_dict.get("manual_crawl_post_url"),
            default=default_actions.manual_crawl_post_url,
        ),
        crawl_jobs_url=_as_non_empty_text(
            actions_dict.get("crawl_jobs_url"),
            default=default_actions.crawl_jobs_url,
        ),
        crawl_errors_url=_as_non_empty_text(
            actions_dict.get("crawl_errors_url"),
            default=default_actions.crawl_errors_url,
        ),
        config_url=_as_non_empty_text(
            actions_dict.get("config_url"),
            default=default_actions.config_url,
        ),
    )


def _normalize_source_sites_active_crawl(
    value: object,
    *,
    code: str,
) -> SourceSiteAdminActiveCrawl:
    if isinstance(value, SourceSiteAdminActiveCrawl):
        return value
    default_detail_url = (
        f"/admin/crawl-jobs?source_code={code}" if code and code != "-" else "/admin/crawl-jobs"
    )
    crawl_dict = value.model_dump() if hasattr(value, "model_dump") else (dict(value) if isinstance(value, dict) else {})
    return SourceSiteAdminActiveCrawl(
        id=_as_int(crawl_dict.get("id")),
        job_type=_as_non_empty_text(crawl_dict.get("job_type"), default=""),
        job_type_label=_as_non_empty_text(crawl_dict.get("job_type_label"), default="抓取任务"),
        status=_as_non_empty_text(crawl_dict.get("status"), default=""),
        status_label=_as_non_empty_text(crawl_dict.get("status_label"), default="抓取中"),
        is_stale=bool(crawl_dict.get("is_stale", False)),
        stage_label=_as_non_empty_text(crawl_dict.get("stage_label"), default="抓取中"),
        summary_text=_as_non_empty_text(crawl_dict.get("summary_text"), default="-"),
        detail_url=_as_non_empty_text(crawl_dict.get("detail_url"), default=default_detail_url),
    )


def _load_active_crawl_map(
    *,
    session: Session,
    source_codes: list[str],
) -> dict[str, SourceSiteAdminActiveCrawl]:
    expired_jobs = reconcile_expired_jobs_in_session(session)
    if expired_jobs:
        session.commit()
    normalized_codes = [code for code in source_codes if code]
    if not normalized_codes:
        return {}

    rows = session.execute(
        select(CrawlJob, SourceSite.code)
        .join(SourceSite, SourceSite.id == CrawlJob.source_site_id)
        .where(
            SourceSite.code.in_(normalized_codes),
            CrawlJob.status.in_(sorted(ACTIVE_CRAWL_JOB_STATUSES)),
        )
        .order_by(SourceSite.code.asc(), CrawlJob.id.desc())
    ).all()

    result: dict[str, SourceSiteAdminActiveCrawl] = {}
    for crawl_job, source_code in rows:
        normalized_source_code = _as_non_empty_text(source_code, default="")
        if not normalized_source_code or normalized_source_code in result:
            continue
        progress = build_crawl_job_progress(crawl_job)
        result[normalized_source_code] = SourceSiteAdminActiveCrawl(
            id=int(crawl_job.id),
            job_type=crawl_job.job_type,
            job_type_label=progress["job_type_label"],
            status=crawl_job.status,
            status_label=progress["status_label"],
            is_stale=bool(progress["is_stale"]),
            stage_label=progress["stage_label"],
            summary_text=progress["summary_text"],
            detail_url=f"/admin/crawl-jobs/{int(crawl_job.id)}",
        )
    return result


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _default_source_form_values() -> dict[str, str]:
    return {
        "source_code": "",
        "source_name": "",
        "official_url": "",
        "list_url": "",
        "remark": "",
        "is_active": "true",
        "schedule_enabled": "false",
        "schedule_days": "1",
        "crawl_interval_minutes": "1440",
        "default_max_pages": "50",
    }


def _source_form_values_from_request(form_data: dict[str, list[str]]) -> dict[str, str]:
    defaults = _default_source_form_values()
    return {
        "source_code": (form_data.get("source_code") or [defaults["source_code"]])[0].strip(),
        "source_name": (form_data.get("source_name") or [defaults["source_name"]])[0].strip(),
        "official_url": (form_data.get("official_url") or [defaults["official_url"]])[0].strip(),
        "list_url": (form_data.get("list_url") or [defaults["list_url"]])[0].strip(),
        "remark": (form_data.get("remark") or [defaults["remark"]])[0].strip(),
        "is_active": (form_data.get("is_active") or [defaults["is_active"]])[0].strip(),
        "schedule_enabled": (form_data.get("schedule_enabled") or [defaults["schedule_enabled"]])[0].strip(),
        "schedule_days": (form_data.get("schedule_days") or [defaults["schedule_days"]])[0].strip(),
        "crawl_interval_minutes": (
            form_data.get("crawl_interval_minutes") or [defaults["crawl_interval_minutes"]]
        )[0].strip(),
        "default_max_pages": (form_data.get("default_max_pages") or [defaults["default_max_pages"]])[0].strip(),
    }


def _safe_parse_form_bool(value: str, *, field_name: str, errors: list[str]) -> bool | None:
    try:
        return _parse_form_bool(value, field_name=field_name)
    except HTTPException as exc:
        errors.append(str(exc.detail))
        return None


def _safe_parse_schedule_days(value: str, *, errors: list[str]) -> int | None:
    try:
        number = int(value.strip())
    except ValueError:
        errors.append("schedule_days must be integer")
        return None
    if number not in {1, 2, 3, 7}:
        errors.append("schedule_days must be one of 1, 2, 3, 7")
        return None
    return number


def _safe_parse_form_positive_int(
    value: str,
    *,
    field_name: str,
    errors: list[str],
) -> int | None:
    try:
        return _parse_form_positive_int(value, field_name=field_name)
    except HTTPException as exc:
        errors.append(str(exc.detail))
        return None


def _safe_parse_optional_positive_int(
    raw_value: str,
    *,
    field_name: str,
    errors: list[str],
) -> int | None:
    normalized = raw_value.strip()
    if not normalized:
        return None
    try:
        return _parse_form_positive_int(normalized, field_name=field_name)
    except HTTPException as exc:
        errors.append(str(exc.detail))
        return None


def _humanize_validation_errors(error: ValidationError) -> list[str]:
    messages: list[str] = []
    for item in error.errors():
        field = ".".join(str(part) for part in item.get("loc", []))
        message = str(item.get("msg", "invalid value"))
        messages.append(f"{field}: {message}")
    return messages


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _manual_crawl_success_redirect_url(*, source_code: str, created_job_id: int) -> str:
    query = urlencode({"source_code": source_code, "created_job_id": created_job_id})
    return f"/admin/crawl-jobs?{query}"


def _manual_crawl_create_error_message(exc: Exception) -> str:
    if isinstance(exc, SourceActiveCrawlJobConflictError):
        return str(exc)
    detail = str(exc).strip()
    if detail:
        return f"手动抓取任务创建失败：{detail}"
    return "手动抓取任务创建失败，请查看服务日志"


def _manual_crawl_error_redirect_url(
    *,
    source_code: str,
    message: str,
    return_to: str,
) -> str:
    if return_to == "source-sites":
        query = urlencode({"manual_crawl_error": message, "source_code": source_code})
        return f"/admin/source-sites?{query}"
    query = urlencode({"manual_crawl_error": message})
    return f"/admin/sources/{source_code}?{query}"
