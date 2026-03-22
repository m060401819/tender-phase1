from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.services import HealthRuleService


def _build_session_factory(tmp_path: Path) -> tuple[sessionmaker, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'health_rule_service.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return session_factory, engine


def test_health_rule_service_default_and_update(tmp_path: Path) -> None:
    session_factory, engine = _build_session_factory(tmp_path)
    try:
        with session_factory() as session:
            service = HealthRuleService(session=session)
            default_rules = service.get_rules()
            assert default_rules.recent_error_warning_threshold == 3
            assert default_rules.recent_error_critical_threshold == 6
            assert default_rules.consecutive_failure_warning_threshold == 1
            assert default_rules.consecutive_failure_critical_threshold == 1
            assert default_rules.partial_warning_enabled is True

            updated = service.update_rules(
                {
                    "recent_error_warning_threshold": 2,
                    "recent_error_critical_threshold": 4,
                    "consecutive_failure_warning_threshold": 1,
                    "consecutive_failure_critical_threshold": 2,
                    "partial_warning_enabled": False,
                }
            )
            assert updated.recent_error_warning_threshold == 2
            assert updated.recent_error_critical_threshold == 4
            assert updated.consecutive_failure_warning_threshold == 1
            assert updated.consecutive_failure_critical_threshold == 2
            assert updated.partial_warning_enabled is False
    finally:
        engine.dispose()


def test_health_rule_service_rejects_invalid_thresholds(tmp_path: Path) -> None:
    session_factory, engine = _build_session_factory(tmp_path)
    try:
        with session_factory() as session:
            service = HealthRuleService(session=session)
            service.get_rules()
            try:
                service.update_rules(
                    {
                        "recent_error_warning_threshold": 7,
                        "recent_error_critical_threshold": 6,
                    }
                )
                raise AssertionError("expected ValueError")
            except ValueError as exc:
                assert "recent_error_warning_threshold" in str(exc)

            try:
                service.update_rules(
                    {
                        "consecutive_failure_warning_threshold": -1,
                    }
                )
                raise AssertionError("expected ValueError")
            except ValueError as exc:
                assert "must be >= 0" in str(exc)
    finally:
        engine.dispose()


def test_health_rule_service_evaluate_health_status_uses_thresholds() -> None:
    class _Rules:
        recent_error_warning_threshold = 2
        recent_error_critical_threshold = 5
        consecutive_failure_warning_threshold = 1
        consecutive_failure_critical_threshold = 2
        partial_warning_enabled = False

    assert (
        HealthRuleService.evaluate_health_status(
            rules=_Rules(),
            latest_status="failed",
            recent_7d_error_count=0,
            consecutive_failure_count=1,
        )
        == "warning"
    )
    assert (
        HealthRuleService.evaluate_health_status(
            rules=_Rules(),
            latest_status="failed",
            recent_7d_error_count=0,
            consecutive_failure_count=2,
        )
        == "critical"
    )
    assert (
        HealthRuleService.evaluate_health_status(
            rules=_Rules(),
            latest_status="partial",
            recent_7d_error_count=0,
            consecutive_failure_count=0,
        )
        == "normal"
    )
