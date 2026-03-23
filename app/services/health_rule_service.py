from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HealthRuleConfig

DEFAULT_HEALTH_RULES = {
    "recent_error_warning_threshold": 3,
    "recent_error_critical_threshold": 6,
    "consecutive_failure_warning_threshold": 1,
    "consecutive_failure_critical_threshold": 1,
    "partial_warning_enabled": True,
}


@dataclass(slots=True)
class HealthRuleSnapshot:
    recent_error_warning_threshold: int
    recent_error_critical_threshold: int
    consecutive_failure_warning_threshold: int
    consecutive_failure_critical_threshold: int
    partial_warning_enabled: bool


class HealthRuleService:
    """Read/update health rule thresholds and evaluate health status."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_rules(self) -> HealthRuleSnapshot:
        model = self._ensure_config()
        return self._to_snapshot(model)

    def update_rules(self, updates: Mapping[str, object]) -> HealthRuleSnapshot:
        model = self._ensure_config()
        candidate = self._to_snapshot(model)
        for key, value in updates.items():
            if key == "partial_warning_enabled":
                candidate.partial_warning_enabled = bool(value)
                continue
            if key == "recent_error_warning_threshold":
                candidate.recent_error_warning_threshold = _coerce_int_value(value)
                continue
            if key == "recent_error_critical_threshold":
                candidate.recent_error_critical_threshold = _coerce_int_value(value)
                continue
            if key == "consecutive_failure_warning_threshold":
                candidate.consecutive_failure_warning_threshold = _coerce_int_value(value)
                continue
            if key == "consecutive_failure_critical_threshold":
                candidate.consecutive_failure_critical_threshold = _coerce_int_value(value)
        self._validate_rules(candidate)

        model.recent_error_warning_threshold = candidate.recent_error_warning_threshold
        model.recent_error_critical_threshold = candidate.recent_error_critical_threshold
        model.consecutive_failure_warning_threshold = candidate.consecutive_failure_warning_threshold
        model.consecutive_failure_critical_threshold = candidate.consecutive_failure_critical_threshold
        model.partial_warning_enabled = candidate.partial_warning_enabled
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_snapshot(model)

    @staticmethod
    def evaluate_health_status(
        *,
        rules: HealthRuleSnapshot,
        latest_status: str | None,
        recent_7d_error_count: int,
        consecutive_failure_count: int,
    ) -> str:
        if recent_7d_error_count >= rules.recent_error_critical_threshold:
            return "critical"
        if consecutive_failure_count >= rules.consecutive_failure_critical_threshold:
            return "critical"
        if latest_status == "failed" and consecutive_failure_count >= 1:
            if rules.consecutive_failure_critical_threshold <= 1:
                return "critical"
            return "warning"

        if recent_7d_error_count >= rules.recent_error_warning_threshold:
            return "warning"
        if consecutive_failure_count >= rules.consecutive_failure_warning_threshold:
            return "warning"
        if latest_status == "partial":
            return "warning" if rules.partial_warning_enabled else "normal"
        if latest_status == "succeeded":
            return "normal"
        return "warning"

    def _ensure_config(self) -> HealthRuleConfig:
        model = self.session.scalar(select(HealthRuleConfig).order_by(HealthRuleConfig.id.asc()))
        if model is not None:
            return model
        model = HealthRuleConfig(
            id=1,
            recent_error_warning_threshold=DEFAULT_HEALTH_RULES["recent_error_warning_threshold"],
            recent_error_critical_threshold=DEFAULT_HEALTH_RULES["recent_error_critical_threshold"],
            consecutive_failure_warning_threshold=DEFAULT_HEALTH_RULES["consecutive_failure_warning_threshold"],
            consecutive_failure_critical_threshold=DEFAULT_HEALTH_RULES["consecutive_failure_critical_threshold"],
            partial_warning_enabled=DEFAULT_HEALTH_RULES["partial_warning_enabled"],
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return model

    @staticmethod
    def _validate_rules(candidate: HealthRuleSnapshot) -> None:
        if candidate.recent_error_warning_threshold < 0:
            raise ValueError("recent_error_warning_threshold must be >= 0")
        if candidate.recent_error_critical_threshold < 0:
            raise ValueError("recent_error_critical_threshold must be >= 0")
        if candidate.consecutive_failure_warning_threshold < 0:
            raise ValueError("consecutive_failure_warning_threshold must be >= 0")
        if candidate.consecutive_failure_critical_threshold < 0:
            raise ValueError("consecutive_failure_critical_threshold must be >= 0")

        if candidate.recent_error_warning_threshold > candidate.recent_error_critical_threshold:
            raise ValueError("recent_error_warning_threshold cannot be greater than recent_error_critical_threshold")
        if candidate.consecutive_failure_warning_threshold > candidate.consecutive_failure_critical_threshold:
            raise ValueError(
                "consecutive_failure_warning_threshold cannot be greater than consecutive_failure_critical_threshold"
            )

    @staticmethod
    def _to_snapshot(model: HealthRuleConfig) -> HealthRuleSnapshot:
        return HealthRuleSnapshot(
            recent_error_warning_threshold=int(model.recent_error_warning_threshold),
            recent_error_critical_threshold=int(model.recent_error_critical_threshold),
            consecutive_failure_warning_threshold=int(model.consecutive_failure_warning_threshold),
            consecutive_failure_critical_threshold=int(model.consecutive_failure_critical_threshold),
            partial_warning_enabled=bool(model.partial_warning_enabled),
        )


def _coerce_int_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    if isinstance(value, (bytes, bytearray)):
        return int(value)
    raise TypeError(f"cannot coerce {type(value).__name__} to int")
