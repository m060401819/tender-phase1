from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.endpoints.settings import get_health_rule_service
from app.core.auth import AuthenticatedUser, get_current_user, render_admin_template, require_admin_csrf
from app.services import HealthRuleService

router = APIRouter(tags=["admin-settings"])
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

_BOOL_TRUE_SET = {"1", "true", "yes", "on"}
_BOOL_FALSE_SET = {"0", "false", "no", "off"}


@router.get("/admin/settings/health-rules", response_class=HTMLResponse)
def admin_health_rule_config_page(
    request: Request,
    service: HealthRuleService = Depends(get_health_rule_service),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> HTMLResponse:
    rules = service.get_rules()
    context = {
        "updated": request.query_params.get("updated") == "1",
        "rules": {
            "recent_error_warning_threshold": rules.recent_error_warning_threshold,
            "recent_error_critical_threshold": rules.recent_error_critical_threshold,
            "consecutive_failure_warning_threshold": rules.consecutive_failure_warning_threshold,
            "consecutive_failure_critical_threshold": rules.consecutive_failure_critical_threshold,
            "partial_warning_enabled": rules.partial_warning_enabled,
        },
    }
    return render_admin_template(
        templates=TEMPLATES,
        request=request,
        name="admin/health_rules_settings.html",
        context=context,
        current_user=current_user,
    )


@router.post("/admin/settings/health-rules")
async def admin_update_health_rule_config(
    request: Request,
    service: HealthRuleService = Depends(get_health_rule_service),
    _csrf_protected: None = Depends(require_admin_csrf),
) -> RedirectResponse:
    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)
    updates = {
        "recent_error_warning_threshold": _parse_non_negative_int(
            (form_data.get("recent_error_warning_threshold") or [""])[0],
            field_name="recent_error_warning_threshold",
        ),
        "recent_error_critical_threshold": _parse_non_negative_int(
            (form_data.get("recent_error_critical_threshold") or [""])[0],
            field_name="recent_error_critical_threshold",
        ),
        "consecutive_failure_warning_threshold": _parse_non_negative_int(
            (form_data.get("consecutive_failure_warning_threshold") or [""])[0],
            field_name="consecutive_failure_warning_threshold",
        ),
        "consecutive_failure_critical_threshold": _parse_non_negative_int(
            (form_data.get("consecutive_failure_critical_threshold") or [""])[0],
            field_name="consecutive_failure_critical_threshold",
        ),
        "partial_warning_enabled": _parse_bool(
            (form_data.get("partial_warning_enabled") or [""])[0],
            field_name="partial_warning_enabled",
        ),
    }
    try:
        service.update_rules(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/admin/settings/health-rules?updated=1", status_code=303)


def _parse_non_negative_int(raw_value: str, *, field_name: str) -> int:
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be integer") from exc
    if value < 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be >= 0")
    return value


def _parse_bool(raw_value: str, *, field_name: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in _BOOL_TRUE_SET:
        return True
    if normalized in _BOOL_FALSE_SET:
        return False
    raise HTTPException(status_code=400, detail=f"{field_name} must be boolean")
