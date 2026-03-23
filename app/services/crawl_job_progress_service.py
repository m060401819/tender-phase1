from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

ACTIVE_CRAWL_JOB_STATUSES = {"pending", "running"}

JOB_TYPE_LABELS = {
    "manual": "手动抓取",
    "scheduled": "自动抓取",
    "backfill": "回填抓取",
    "manual_retry": "重试抓取",
}

STATUS_LABELS = {
    "pending": "排队中",
    "running": "抓取中",
    "succeeded": "已完成",
    "failed": "失败",
    "partial": "部分成功",
}


def build_crawl_job_progress(job: object) -> dict[str, object]:
    status = _as_text(_read(job, "status"), default="-")
    job_type = _as_text(_read(job, "job_type"), default="-")
    pages_fetched = _as_int(_read(job, "pages_fetched"))
    documents_saved = _as_int(_read(job, "documents_saved"))
    notices_upserted = _as_int(_read(job, "notices_upserted"))
    error_count = _as_int(_read(job, "error_count"))
    list_items_seen = _as_int(_read(job, "list_items_seen"))
    list_items_unique = _as_int(_read(job, "list_items_unique"))
    detail_pages_fetched = _as_int(_read(job, "detail_pages_fetched"))
    dedup_skipped = _as_int(_read(job, "list_items_source_duplicates_skipped")) + _as_int(
        _read(job, "source_duplicates_suppressed")
    )
    picked_at = _as_datetime(_read(job, "picked_at"))
    heartbeat_at = _as_datetime(_read(job, "heartbeat_at"))
    timeout_at = _as_datetime(_read(job, "timeout_at")) or _as_datetime(_read(job, "lease_expires_at"))
    is_stale = _is_stale(status=status, timeout_at=timeout_at)

    is_active = status == "pending" or (status == "running" and not is_stale)
    job_type_label = JOB_TYPE_LABELS.get(job_type, job_type or "-")
    status_label = STATUS_LABELS.get(status, status or "-")

    if is_stale and status == "pending":
        stage_label = "等待重派发"
        summary_text = "任务派发租约已过期，等待独立 dispatcher 重试"
    elif is_stale and status == "running":
        stage_label = "心跳超时"
        summary_text = "任务心跳已过期，执行进程可能已退出或卡死"
    elif status == "pending":
        if picked_at is not None:
            stage_label = "等待 Worker 启动"
            summary_text = "dispatcher 已领取任务，等待 worker 启动"
        else:
            stage_label = "等待启动"
            summary_text = "已入队，等待启动"
    elif status == "running":
        if detail_pages_fetched > 0 or documents_saved > 0 or notices_upserted > 0:
            stage_label = "抓取详情与入库"
        elif list_items_seen > 0 or list_items_unique > 0:
            stage_label = "解析列表页"
        elif pages_fetched > 0:
            stage_label = "抓取列表页"
        else:
            stage_label = "启动 Spider"
        summary_text = _join_parts(
            [
                _metric("列表页", pages_fetched, positive_only=True),
                _metric("列表项", list_items_seen, positive_only=True),
                _metric("唯一项", list_items_unique, positive_only=True),
                _metric("详情页", detail_pages_fetched, positive_only=True),
                _metric("公告", notices_upserted, positive_only=True),
                _metric("归档", documents_saved, positive_only=True),
                _metric("去重跳过", dedup_skipped, positive_only=True),
                _metric("错误", error_count, positive_only=True),
            ],
            fallback=f"{job_type_label}已启动，正在持续更新统计",
        )
    else:
        stage_label = status_label
        summary_text = _join_parts(
            [
                _metric("列表页", pages_fetched),
                _metric("列表项", list_items_seen),
                _metric("唯一项", list_items_unique),
                _metric("详情页", detail_pages_fetched),
                _metric("公告", notices_upserted),
                _metric("归档", documents_saved),
                _metric("去重跳过", dedup_skipped),
                _metric("错误", error_count),
            ],
            fallback="-",
        )

    return {
        "is_active": is_active,
        "is_stale": is_stale,
        "job_type_label": job_type_label,
        "status_label": status_label,
        "stage_label": stage_label,
        "summary_text": summary_text,
        "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at is not None else None,
        "timeout_at": timeout_at.isoformat() if timeout_at is not None else None,
        "lease_expires_at": timeout_at.isoformat() if timeout_at is not None else None,
    }


def _read(job: object, field: str) -> Any:
    if isinstance(job, dict):
        return job.get(field)
    return getattr(job, field, None)


def _as_text(value: object, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, Enum):
        value = value.value
    text = str(value).strip()
    if not text:
        return default
    return text


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


def _metric(label: str, value: int, *, positive_only: bool = False) -> str | None:
    if positive_only and value <= 0:
        return None
    return f"{label} {value}"


def _join_parts(parts: list[str | None], *, fallback: str) -> str:
    normalized = [part for part in parts if part]
    if not normalized:
        return fallback
    return " / ".join(normalized)


def _is_stale(*, status: str, timeout_at: datetime | None) -> bool:
    if status not in ACTIVE_CRAWL_JOB_STATUSES:
        return False
    if timeout_at is None:
        return False
    return timeout_at <= datetime.now(timezone.utc)
