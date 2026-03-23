from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def build_job_params_payload(
    *,
    source_code: str,
    job_type: str,
    triggered_by: str | None = None,
    max_pages: int | None = None,
    backfill_year: int | None = None,
    retry_of_job_id: int | None = None,
    spider_name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_code": source_code,
        "job_type": job_type,
    }
    if triggered_by:
        payload["triggered_by"] = triggered_by
    if max_pages is not None:
        payload["max_pages"] = int(max_pages)
    if backfill_year is not None:
        payload["backfill_year"] = int(backfill_year)
    if retry_of_job_id is not None:
        payload["retry_of_job_id"] = int(retry_of_job_id)
    if spider_name:
        payload["spider_name"] = spider_name
    return payload


def build_runtime_stats_payload(
    *,
    run_stage: str,
    spider_name: str | None = None,
    pages_scraped: int | None = None,
    list_seen: int | None = None,
    list_unique: int | None = None,
    detail_requests: int | None = None,
    dedup_skipped: int | None = None,
    notices_written: int | None = None,
    raw_documents_written: int | None = None,
    first_publish_date_seen: str | None = None,
    last_publish_date_seen: str | None = None,
    return_code: int | None = None,
    timeout_stage: str | None = None,
    heartbeat_at: datetime | None = None,
    timeout_at: datetime | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_stage": run_stage,
    }
    if spider_name:
        payload["spider_name"] = spider_name
    if pages_scraped is not None:
        payload["pages_scraped"] = int(pages_scraped)
    if list_seen is not None:
        payload["list_seen"] = int(list_seen)
    if list_unique is not None:
        payload["list_unique"] = int(list_unique)
    if detail_requests is not None:
        payload["detail_requests"] = int(detail_requests)
    if dedup_skipped is not None:
        payload["dedup_skipped"] = int(dedup_skipped)
    if notices_written is not None:
        payload["notices_written"] = int(notices_written)
    if raw_documents_written is not None:
        payload["raw_documents_written"] = int(raw_documents_written)
    if first_publish_date_seen:
        payload["first_publish_date_seen"] = first_publish_date_seen
    if last_publish_date_seen:
        payload["last_publish_date_seen"] = last_publish_date_seen
    if return_code is not None:
        payload["return_code"] = int(return_code)
    if timeout_stage:
        payload["timeout_stage"] = timeout_stage
    if heartbeat_at is not None:
        payload["heartbeat_at"] = heartbeat_at.isoformat()
    if timeout_at is not None:
        payload["timeout_at"] = timeout_at.isoformat()
    return payload


def read_payload_int(payload: Mapping[str, Any] | None, key: str) -> int | None:
    if not payload:
        return None
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def read_payload_text(payload: Mapping[str, Any] | None, key: str) -> str | None:
    if not payload:
        return None
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
