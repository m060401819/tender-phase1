"""add crawl_job source mutex

Revision ID: 20260322_0011
Revises: 20260322_0010
Create Date: 2026-03-22 17:45:00

"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260322_0011"
down_revision: Union[str, None] = "20260322_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIVE_STATUSES_SQL = "('pending', 'running')"
_MUTEX_INDEX_NAME = "uq_crawl_job_source_active"


def upgrade() -> None:
    conn = op.get_bind()
    _collapse_legacy_active_duplicates(conn)
    op.create_index(
        _MUTEX_INDEX_NAME,
        "crawl_job",
        ["source_site_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN {_ACTIVE_STATUSES_SQL}"),
        sqlite_where=sa.text(f"status IN {_ACTIVE_STATUSES_SQL}"),
    )


def downgrade() -> None:
    op.drop_index(_MUTEX_INDEX_NAME, table_name="crawl_job")


def _collapse_legacy_active_duplicates(conn) -> None:  # type: ignore[no-untyped-def]
    duplicate_source_ids = [
        int(row[0])
        for row in conn.execute(
            sa.text(
                f"""
                SELECT source_site_id
                FROM crawl_job
                WHERE status IN {_ACTIVE_STATUSES_SQL}
                GROUP BY source_site_id
                HAVING COUNT(*) > 1
                """
            )
        ).all()
    ]
    if not duplicate_source_ids:
        return

    moment = datetime.now(timezone.utc)
    for source_site_id in duplicate_source_ids:
        active_rows = conn.execute(
            sa.text(
                f"""
                SELECT id, message
                FROM crawl_job
                WHERE source_site_id = :source_site_id
                  AND status IN {_ACTIVE_STATUSES_SQL}
                ORDER BY COALESCE(picked_at, started_at, queued_at, created_at) DESC, id DESC
                """
            ),
            {"source_site_id": source_site_id},
        ).mappings().all()
        if len(active_rows) < 2:
            continue

        keep_job_id = int(active_rows[0]["id"])
        for row in active_rows[1:]:
            failure_message = _append_message(
                row.get("message"),
                (
                    "run_stage=source_mutex_migration; "
                    f"failure_reason=来源级互斥迁移修复：同一来源仅保留最新活跃任务 #{keep_job_id}"
                ),
            )
            conn.execute(
                sa.text(
                    """
                    UPDATE crawl_job
                    SET status = 'failed',
                        started_at = COALESCE(started_at, picked_at, queued_at, created_at, :moment),
                        finished_at = :moment,
                        heartbeat_at = COALESCE(heartbeat_at, :moment),
                        timeout_at = NULL,
                        lease_expires_at = NULL,
                        message = :message
                    WHERE id = :job_id
                    """
                ),
                {
                    "moment": moment,
                    "message": failure_message,
                    "job_id": int(row["id"]),
                },
            )


def _append_message(existing: object, extra: str) -> str:
    original = str(existing or "").strip()
    if not original:
        return extra
    return f"{original}; {extra}"
