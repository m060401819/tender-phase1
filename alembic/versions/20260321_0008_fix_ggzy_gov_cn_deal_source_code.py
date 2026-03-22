"""normalize ggzy source code to ggzy_gov_cn_deal

Revision ID: 20260321_0008
Revises: 20260320_0007
Create Date: 2026-03-21 19:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260321_0008"
down_revision: Union[str, None] = "20260320_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    candidate_rows = bind.execute(
        sa.text(
            """
            SELECT id, code
            FROM source_site
            WHERE (
                code IN ('2', 'ggzy_gov_cn', 'ggzy_gov_cn_deal')
                OR name LIKE '%全国公共资源交易平台%'
            )
            ORDER BY
                CASE
                    WHEN code = '2' THEN 0
                    WHEN code = 'ggzy_gov_cn' THEN 1
                    WHEN code = 'ggzy_gov_cn_deal' THEN 2
                    ELSE 3
                END,
                id ASC
            """
        )
    ).all()
    if not candidate_rows:
        return

    target_id = int(candidate_rows[0][0])

    existing_target = bind.execute(
        sa.text("SELECT id FROM source_site WHERE code = 'ggzy_gov_cn_deal' LIMIT 1")
    ).first()
    if existing_target is not None and int(existing_target[0]) != target_id:
        bind.execute(
            sa.text(
                "UPDATE source_site SET code = :legacy_code WHERE id = :source_id"
            ),
            {
                "legacy_code": f"ggzy_gov_cn_deal_legacy_{int(existing_target[0])}",
                "source_id": int(existing_target[0]),
            },
        )

    bind.execute(
        sa.text(
            """
            UPDATE source_site
            SET
                code = 'ggzy_gov_cn_deal',
                name = CASE
                    WHEN name IS NULL OR name = '' THEN '全国公共资源交易平台（政府采购）'
                    ELSE name
                END,
                base_url = 'https://www.ggzy.gov.cn/',
                official_url = 'https://www.ggzy.gov.cn/',
                list_url = 'https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02',
                default_max_pages = CASE
                    WHEN default_max_pages IS NULL OR default_max_pages < 1 THEN 50
                    ELSE default_max_pages
                END
            WHERE id = :target_id
            """
        ),
        {"target_id": target_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE source_site
            SET code = 'ggzy_gov_cn'
            WHERE code = 'ggzy_gov_cn_deal'
              AND name LIKE '%全国公共资源交易平台%'
            """
        )
    )
