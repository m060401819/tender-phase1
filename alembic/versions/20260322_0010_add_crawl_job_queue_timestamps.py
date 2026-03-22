"""add crawl_job queue timestamps

Revision ID: 20260322_0010
Revises: 20260322_0009
Create Date: 2026-03-22 16:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260322_0010"
down_revision: Union[str, None] = "20260322_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.add_column(sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("picked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_crawl_job_timeout_at", ["timeout_at"], unique=False)

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE crawl_job SET queued_at = COALESCE(queued_at, created_at)"))
    conn.execute(sa.text("UPDATE crawl_job SET timeout_at = COALESCE(timeout_at, lease_expires_at)"))
    conn.execute(
        sa.text(
            """
            UPDATE crawl_job
            SET picked_at = COALESCE(picked_at, started_at)
            WHERE status IN ('running', 'succeeded', 'failed', 'partial')
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.drop_index("ix_crawl_job_timeout_at")
        batch_op.drop_column("timeout_at")
        batch_op.drop_column("picked_at")
        batch_op.drop_column("queued_at")
