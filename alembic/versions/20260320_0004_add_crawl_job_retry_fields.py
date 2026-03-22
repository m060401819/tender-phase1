"""add crawl_job retry fields

Revision ID: 20260320_0004
Revises: 20260320_0003
Create Date: 2026-03-20 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0004"
down_revision: Union[str, None] = "20260320_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.add_column(sa.Column("retry_of_job_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_crawl_job_retry_of_job_id",
            "crawl_job",
            ["retry_of_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint("uq_crawl_job_retry_of_job_id", ["retry_of_job_id"])
        batch_op.create_index("ix_crawl_job_retry_of_job_id", ["retry_of_job_id"], unique=False)
        batch_op.drop_constraint("ck_crawl_job_type", type_="check")
        batch_op.create_check_constraint(
            "ck_crawl_job_type",
            "job_type IN ('scheduled', 'manual', 'backfill', 'manual_retry')",
        )


def downgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.drop_constraint("ck_crawl_job_type", type_="check")
        batch_op.create_check_constraint(
            "ck_crawl_job_type",
            "job_type IN ('scheduled', 'manual', 'backfill')",
        )
        batch_op.drop_index("ix_crawl_job_retry_of_job_id")
        batch_op.drop_constraint("uq_crawl_job_retry_of_job_id", type_="unique")
        batch_op.drop_constraint("fk_crawl_job_retry_of_job_id", type_="foreignkey")
        batch_op.drop_column("retry_of_job_id")
