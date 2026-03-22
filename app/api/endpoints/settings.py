from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import HealthRuleConfigPatchRequest, HealthRuleConfigResponse
from app.db.session import get_db
from app.services import HealthRuleService

router = APIRouter(tags=["settings"])


def get_health_rule_service(db: Session = Depends(get_db)) -> HealthRuleService:
    return HealthRuleService(session=db)


@router.get("/settings/health-rules", response_model=HealthRuleConfigResponse)
def get_health_rules(
    service: HealthRuleService = Depends(get_health_rule_service),
) -> HealthRuleConfigResponse:
    rules = service.get_rules()
    return HealthRuleConfigResponse(
        recent_error_warning_threshold=rules.recent_error_warning_threshold,
        recent_error_critical_threshold=rules.recent_error_critical_threshold,
        consecutive_failure_warning_threshold=rules.consecutive_failure_warning_threshold,
        consecutive_failure_critical_threshold=rules.consecutive_failure_critical_threshold,
        partial_warning_enabled=rules.partial_warning_enabled,
    )


@router.patch("/settings/health-rules", response_model=HealthRuleConfigResponse)
def patch_health_rules(
    payload: HealthRuleConfigPatchRequest,
    service: HealthRuleService = Depends(get_health_rule_service),
) -> HealthRuleConfigResponse:
    updates = payload.model_dump(exclude_unset=True)
    try:
        rules = service.update_rules(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HealthRuleConfigResponse(
        recent_error_warning_threshold=rules.recent_error_warning_threshold,
        recent_error_critical_threshold=rules.recent_error_critical_threshold,
        consecutive_failure_warning_threshold=rules.consecutive_failure_warning_threshold,
        consecutive_failure_critical_threshold=rules.consecutive_failure_critical_threshold,
        partial_warning_enabled=rules.partial_warning_enabled,
    )
