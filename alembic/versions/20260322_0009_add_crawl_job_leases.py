"""add crawl_job lease fields

Revision ID: 20260322_0009
Revises: 20260321_0008
Create Date: 2026-03-22 14:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260322_0009"
down_revision: Union[str, None] = "20260321_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_crawl_job_lease_expires_at", ["lease_expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.drop_index("ix_crawl_job_lease_expires_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("heartbeat_at")
