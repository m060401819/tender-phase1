"""add health_rule_config table

Revision ID: 20260320_0005
Revises: 20260320_0004
Create Date: 2026-03-20 23:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0005"
down_revision: Union[str, None] = "20260320_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_rule_config",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recent_error_warning_threshold", sa.Integer(), server_default="3", nullable=False),
        sa.Column("recent_error_critical_threshold", sa.Integer(), server_default="6", nullable=False),
        sa.Column("consecutive_failure_warning_threshold", sa.Integer(), server_default="1", nullable=False),
        sa.Column("consecutive_failure_critical_threshold", sa.Integer(), server_default="1", nullable=False),
        sa.Column("partial_warning_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recent_error_warning_threshold >= 0",
            name="ck_health_rule_recent_error_warning_non_negative",
        ),
        sa.CheckConstraint(
            "recent_error_critical_threshold >= 0",
            name="ck_health_rule_recent_error_critical_non_negative",
        ),
        sa.CheckConstraint(
            "recent_error_warning_threshold <= recent_error_critical_threshold",
            name="ck_health_rule_recent_error_warning_le_critical",
        ),
        sa.CheckConstraint(
            "consecutive_failure_warning_threshold >= 0",
            name="ck_health_rule_consecutive_warning_non_negative",
        ),
        sa.CheckConstraint(
            "consecutive_failure_critical_threshold >= 0",
            name="ck_health_rule_consecutive_critical_non_negative",
        ),
        sa.CheckConstraint(
            "consecutive_failure_warning_threshold <= consecutive_failure_critical_threshold",
            name="ck_health_rule_consecutive_warning_le_critical",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("health_rule_config")
