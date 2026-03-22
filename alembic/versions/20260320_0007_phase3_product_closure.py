"""phase3 product closure fields

Revision ID: 20260320_0007
Revises: 20260320_0006
Create Date: 2026-03-20 16:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0007"
down_revision: Union[str, None] = "20260320_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("source_site") as batch_op:
        batch_op.add_column(sa.Column("official_url", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("list_url", sa.Text(), server_default="", nullable=False))

    op.execute("UPDATE source_site SET official_url = base_url WHERE official_url = '' OR official_url IS NULL")
    op.execute("UPDATE source_site SET list_url = base_url WHERE list_url = '' OR list_url IS NULL")
    op.execute("UPDATE source_site SET default_max_pages = 50 WHERE code = 'anhui_ggzy_zfcg' AND default_max_pages = 1")
    op.execute("UPDATE source_site SET default_max_pages = 50 WHERE default_max_pages IS NULL OR default_max_pages < 1")

    with op.batch_alter_table("source_site") as batch_op:
        batch_op.alter_column("default_max_pages", server_default=sa.text("50"))

    with op.batch_alter_table("tender_notice") as batch_op:
        batch_op.add_column(sa.Column("dedup_key", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_tender_notice_dedup_key", ["dedup_key"], unique=False)

    op.execute("UPDATE tender_notice SET dedup_key = COALESCE(source_duplicate_key, dedup_hash)")

    with op.batch_alter_table("notice_version") as batch_op:
        batch_op.add_column(sa.Column("dedup_key", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_notice_version_dedup_key", ["dedup_key"], unique=False)

    op.execute("UPDATE notice_version SET dedup_key = source_duplicate_key")


def downgrade() -> None:
    with op.batch_alter_table("notice_version") as batch_op:
        batch_op.drop_index("ix_notice_version_dedup_key")
        batch_op.drop_column("dedup_key")

    with op.batch_alter_table("tender_notice") as batch_op:
        batch_op.drop_index("ix_tender_notice_dedup_key")
        batch_op.drop_column("dedup_key")

    with op.batch_alter_table("source_site") as batch_op:
        batch_op.alter_column("default_max_pages", server_default=sa.text("1"))
        batch_op.drop_column("list_url")
        batch_op.drop_column("official_url")
