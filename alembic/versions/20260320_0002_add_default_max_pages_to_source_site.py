"""add default_max_pages to source_site

Revision ID: 20260320_0002
Revises: 20260319_0001
Create Date: 2026-03-20 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260320_0002"
down_revision: Union[str, None] = "20260319_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_site",
        sa.Column("default_max_pages", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("source_site", "default_max_pages")
