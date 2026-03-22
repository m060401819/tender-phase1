from __future__ import annotations

from pydantic import BaseModel


class HealthRuleConfigResponse(BaseModel):
    recent_error_warning_threshold: int
    recent_error_critical_threshold: int
    consecutive_failure_warning_threshold: int
    consecutive_failure_critical_threshold: int
    partial_warning_enabled: bool


class HealthRuleConfigPatchRequest(BaseModel):
    recent_error_warning_threshold: int | None = None
    recent_error_critical_threshold: int | None = None
    consecutive_failure_warning_threshold: int | None = None
    consecutive_failure_critical_threshold: int | None = None
    partial_warning_enabled: bool | None = None
