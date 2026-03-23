"""add crawl_job structured context

Revision ID: 20260323_0012
Revises: 20260322_0011
Create Date: 2026-03-23 09:30:00

"""
from __future__ import annotations

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260323_0012"
down_revision: Union[str, None] = "20260322_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("crawl_job", sa.Column("job_params_json", sa.JSON(), nullable=True))
    op.add_column("crawl_job", sa.Column("runtime_stats_json", sa.JSON(), nullable=True))
    op.add_column("crawl_job", sa.Column("failure_reason", sa.Text(), nullable=True))
    _backfill_structured_context()


def downgrade() -> None:
    op.drop_column("crawl_job", "failure_reason")
    op.drop_column("crawl_job", "runtime_stats_json")
    op.drop_column("crawl_job", "job_params_json")


def _backfill_structured_context() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT
                job.id,
                src.code AS source_code,
                job.job_type,
                job.status,
                job.triggered_by,
                job.retry_of_job_id,
                job.message
            FROM crawl_job AS job
            JOIN source_site AS src
              ON src.id = job.source_site_id
            ORDER BY job.id ASC
            """
        )
    ).mappings().all()
    if not rows:
        return

    crawl_job = sa.table(
        "crawl_job",
        sa.column("id", sa.BigInteger()),
        sa.column("job_params_json", sa.JSON()),
        sa.column("runtime_stats_json", sa.JSON()),
        sa.column("failure_reason", sa.Text()),
        sa.column("message", sa.Text()),
    )

    for row in rows:
        fields = _parse_legacy_message_fields(row.get("message"))
        job_params = _build_job_params_payload(row=row, fields=fields)
        runtime_stats = _build_runtime_stats_payload(row=row, fields=fields)
        failure_reason = _build_failure_reason(row=row, fields=fields)
        human_message = _build_human_message(
            job_type=str(row["job_type"]),
            status=str(row["status"]),
            fields=fields,
            fallback_message=_normalize_text(row.get("message")),
            failure_reason=failure_reason,
        )
        conn.execute(
            sa.update(crawl_job)
            .where(crawl_job.c.id == sa.bindparam("target_id"))
            .values(
                job_params_json=sa.bindparam("job_params_json"),
                runtime_stats_json=sa.bindparam("runtime_stats_json"),
                failure_reason=sa.bindparam("failure_reason"),
                message=sa.bindparam("message"),
            ),
            [
                {
                    "target_id": int(row["id"]),
                    "job_params_json": job_params,
                    "runtime_stats_json": runtime_stats,
                    "failure_reason": failure_reason,
                    "message": human_message,
                }
            ],
        )


def _build_job_params_payload(*, row, fields: dict[str, str]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    payload: dict[str, Any] = {
        "source_code": str(row["source_code"]),
        "job_type": str(row["job_type"]),
    }
    triggered_by = _normalize_text(row.get("triggered_by"))
    if triggered_by:
        payload["triggered_by"] = triggered_by
    max_pages = _as_int(fields.get("max_pages"))
    if max_pages is not None:
        payload["max_pages"] = max_pages
    backfill_year = _as_int(fields.get("backfill_year"))
    if backfill_year is not None:
        payload["backfill_year"] = backfill_year
    retry_of_job_id = row.get("retry_of_job_id")
    if retry_of_job_id is not None:
        payload["retry_of_job_id"] = int(retry_of_job_id)
    spider_name = _normalize_placeholder(fields.get("spider"))
    if spider_name:
        payload["spider_name"] = spider_name
    return payload


def _build_runtime_stats_payload(*, row, fields: dict[str, str]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    payload: dict[str, Any] = {
        "run_stage": _infer_run_stage(status=str(row["status"]), fields=fields),
    }
    for key in (
        "pages_scraped",
        "list_seen",
        "list_unique",
        "detail_requests",
        "dedup_skipped",
        "notices_written",
        "raw_documents_written",
        "return_code",
    ):
        value = _as_int(fields.get(key))
        if value is not None:
            payload[key] = value

    for key in ("first_publish_date_seen", "last_publish_date_seen", "timeout_stage"):
        value = _normalize_placeholder(fields.get(key))
        if value:
            payload[key] = value

    spider_name = _normalize_placeholder(fields.get("spider"))
    if spider_name:
        payload["spider_name"] = spider_name

    heartbeat_at = _normalize_placeholder(fields.get("heartbeat_at"))
    if heartbeat_at:
        payload["heartbeat_at"] = heartbeat_at
    timeout_at = _normalize_placeholder(fields.get("timeout_at"))
    if timeout_at:
        payload["timeout_at"] = timeout_at
    return payload


def _build_failure_reason(*, row, fields: dict[str, str]) -> str | None:  # type: ignore[no-untyped-def]
    failure_reason = _normalize_placeholder(fields.get("failure_reason"))
    if failure_reason:
        return failure_reason

    message = _normalize_text(row.get("message"))
    if str(row["status"]) in {"failed", "partial"} and message and "=" not in message:
        return message
    return None


def _build_human_message(
    *,
    job_type: str,
    status: str,
    fields: dict[str, str],
    fallback_message: str | None,
    failure_reason: str | None,
) -> str | None:
    if not fields:
        return fallback_message

    run_stage = _infer_run_stage(status=status, fields=fields)
    if run_stage == "queued":
        parts = [f"{job_type} 任务已入队，等待后台调度执行"]
        max_pages = _as_int(fields.get("max_pages"))
        if max_pages is not None:
            parts.append(f"最大页数 {max_pages}")
        backfill_year = _as_int(fields.get("backfill_year"))
        if backfill_year is not None:
            parts.append(f"回填年份 {backfill_year}")
        return "，".join(parts)

    if run_stage == "running":
        spider_name = _normalize_placeholder(fields.get("spider"))
        if spider_name:
            return f"{job_type} 任务执行中（spider={spider_name}）"
        return f"{job_type} 任务执行中"

    if run_stage in {"runner_error", "worker_error", "dispatch_abandoned", "dispatch_failed"} and failure_reason:
        return f"{job_type} 任务在 {run_stage} 阶段失败：{failure_reason}"

    timeout_stage = _normalize_placeholder(fields.get("timeout_stage"))
    if timeout_stage == "pending" and failure_reason:
        return f"任务已放弃启动：{failure_reason}"
    if timeout_stage == "running" and failure_reason:
        return f"任务执行超时：{failure_reason}"

    pages_scraped = _as_int(fields.get("pages_scraped")) or 0
    list_unique = _as_int(fields.get("list_unique")) or 0
    list_seen = _as_int(fields.get("list_seen")) or 0
    detail_requests = _as_int(fields.get("detail_requests")) or 0
    notices_written = _as_int(fields.get("notices_written")) or 0
    raw_documents_written = _as_int(fields.get("raw_documents_written")) or 0
    dedup_skipped = _as_int(fields.get("dedup_skipped")) or 0
    parts = [
        f"{job_type} 任务已结束",
        f"状态 {status}",
        f"列表页 {pages_scraped}",
        f"列表项 {list_unique}/{list_seen}",
        f"详情请求 {detail_requests}",
        f"公告 {notices_written}",
        f"归档 {raw_documents_written}",
        f"去重跳过 {dedup_skipped}",
    ]
    first_publish_date_seen = _normalize_placeholder(fields.get("first_publish_date_seen"))
    if first_publish_date_seen:
        parts.append(f"最早发布日期 {first_publish_date_seen}")
    last_publish_date_seen = _normalize_placeholder(fields.get("last_publish_date_seen"))
    if last_publish_date_seen:
        parts.append(f"最晚发布日期 {last_publish_date_seen}")
    if failure_reason:
        parts.append(f"异常 {failure_reason}")
    return_code = _as_int(fields.get("return_code"))
    if return_code is not None:
        parts.append(f"退出码 {return_code}")
    return "，".join(parts)


def _infer_run_stage(*, status: str, fields: dict[str, str]) -> str:
    run_stage = _normalize_placeholder(fields.get("run_stage"))
    if run_stage:
        return run_stage
    if _normalize_placeholder(fields.get("timeout_stage")):
        return "expired"
    if status == "pending":
        return "queued"
    if status == "running":
        return "running"
    return "finished"


def _parse_legacy_message_fields(message: object) -> dict[str, str]:
    text = _normalize_text(message)
    if not text:
        return {}

    parsed: dict[str, str] = {}
    for part in text.split(";"):
        chunk = part.strip()
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", maxsplit=1)
        key = key.strip()
        if not key:
            continue
        parsed[key] = value.strip()
    return parsed


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_placeholder(value: object) -> str | None:
    text = _normalize_text(value)
    if not text or text == "-":
        return None
    return text


def _as_int(value: object) -> int | None:
    text = _normalize_text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None
