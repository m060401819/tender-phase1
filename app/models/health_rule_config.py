from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class HealthRuleConfig(TimestampMixin, Base):
    """Configurable thresholds for source health status evaluation."""

    __tablename__ = "health_rule_config"
    __table_args__ = (
        CheckConstraint(
            "recent_error_warning_threshold >= 0",
            name="ck_health_rule_recent_error_warning_non_negative",
        ),
        CheckConstraint(
            "recent_error_critical_threshold >= 0",
            name="ck_health_rule_recent_error_critical_non_negative",
        ),
        CheckConstraint(
            "recent_error_warning_threshold <= recent_error_critical_threshold",
            name="ck_health_rule_recent_error_warning_le_critical",
        ),
        CheckConstraint(
            "consecutive_failure_warning_threshold >= 0",
            name="ck_health_rule_consecutive_warning_non_negative",
        ),
        CheckConstraint(
            "consecutive_failure_critical_threshold >= 0",
            name="ck_health_rule_consecutive_critical_non_negative",
        ),
        CheckConstraint(
            "consecutive_failure_warning_threshold <= consecutive_failure_critical_threshold",
            name="ck_health_rule_consecutive_warning_le_critical",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recent_error_warning_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
    )
    recent_error_critical_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=6,
        server_default="6",
    )
    consecutive_failure_warning_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    consecutive_failure_critical_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    partial_warning_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
