"""add source dedup keys and crawl quality stats

Revision ID: 20260320_0006
Revises: 20260320_0005
Create Date: 2026-03-20 23:55:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0006"
down_revision: Union[str, None] = "20260320_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.add_column(sa.Column("list_items_seen", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("list_items_unique", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(
            sa.Column("list_items_source_duplicates_skipped", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("detail_pages_fetched", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("records_inserted", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("records_updated", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("source_duplicates_suppressed", sa.Integer(), server_default="0", nullable=False))

    with op.batch_alter_table("raw_document") as batch_op:
        batch_op.add_column(sa.Column("source_duplicate_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("source_list_item_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_raw_document_source_duplicate_key", ["source_duplicate_key"], unique=False)
        batch_op.create_index(
            "ix_raw_document_source_list_item_fingerprint",
            ["source_list_item_fingerprint"],
            unique=False,
        )

    with op.batch_alter_table("tender_notice") as batch_op:
        batch_op.add_column(sa.Column("source_duplicate_key", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_tender_notice_source_duplicate_key", ["source_duplicate_key"], unique=False)

    with op.batch_alter_table("notice_version") as batch_op:
        batch_op.add_column(sa.Column("source_duplicate_key", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_notice_version_source_duplicate_key", ["source_duplicate_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("notice_version") as batch_op:
        batch_op.drop_index("ix_notice_version_source_duplicate_key")
        batch_op.drop_column("source_duplicate_key")

    with op.batch_alter_table("tender_notice") as batch_op:
        batch_op.drop_index("ix_tender_notice_source_duplicate_key")
        batch_op.drop_column("source_duplicate_key")

    with op.batch_alter_table("raw_document") as batch_op:
        batch_op.drop_index("ix_raw_document_source_list_item_fingerprint")
        batch_op.drop_index("ix_raw_document_source_duplicate_key")
        batch_op.drop_column("source_list_item_fingerprint")
        batch_op.drop_column("source_duplicate_key")

    with op.batch_alter_table("crawl_job") as batch_op:
        batch_op.drop_column("source_duplicates_suppressed")
        batch_op.drop_column("records_updated")
        batch_op.drop_column("records_inserted")
        batch_op.drop_column("detail_pages_fetched")
        batch_op.drop_column("list_items_source_duplicates_skipped")
        batch_op.drop_column("list_items_unique")
        batch_op.drop_column("list_items_seen")
