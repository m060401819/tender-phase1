"""add source schedule fields

Revision ID: 20260320_0003
Revises: 20260320_0002
Create Date: 2026-03-20 15:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0003"
down_revision: Union[str, None] = "20260320_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_site",
        sa.Column("schedule_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "source_site",
        sa.Column("schedule_days", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("source_site", sa.Column("last_scheduled_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("source_site", sa.Column("next_scheduled_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("source_site", sa.Column("last_schedule_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("source_site", "last_schedule_status")
    op.drop_column("source_site", "next_scheduled_run_at")
    op.drop_column("source_site", "last_scheduled_run_at")
    op.drop_column("source_site", "schedule_days")
    op.drop_column("source_site", "schedule_enabled")
