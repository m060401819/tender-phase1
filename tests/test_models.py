from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.db.base import Base
from app.models import NoticeVersion, RawDocument, TenderAttachment, TenderNotice


def _table(name: str):
    return Base.metadata.tables[name]


def _unique_sets(table_name: str) -> set[tuple[str, ...]]:
    table = _table(table_name)
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _check_sql(table_name: str) -> list[str]:
    table = _table(table_name)
    return [str(constraint.sqltext) for constraint in table.constraints if isinstance(constraint, CheckConstraint)]


def _index(table_name: str, name: str) -> Index:
    table = _table(table_name)
    for index in table.indexes:
        if index.name == name:
            return index
    raise AssertionError(f"index not found: {table_name}.{name}")


def test_phase1_core_tables_are_registered() -> None:
    expected = {
        "source_site",
        "crawl_job",
        "raw_document",
        "tender_notice",
        "tender_attachment",
        "notice_version",
        "crawl_error",
        "health_rule_config",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))


def test_raw_document_dedup_constraints_exist() -> None:
    assert ("source_site_id", "url_hash") in _unique_sets("raw_document")
    assert "content_hash" in _table("raw_document").c
    assert "source_duplicate_key" in _table("raw_document").c
    assert "source_list_item_fingerprint" in _table("raw_document").c


def test_tender_notice_core_fields_exist() -> None:
    table = _table("tender_notice")
    for column in ["notice_type", "published_at", "deadline_at", "region", "issuer", "budget_amount", "dedup_key"]:
        assert column in table.c


def test_source_site_runtime_config_fields_exist() -> None:
    table = _table("source_site")
    for column in [
        "official_url",
        "list_url",
        "is_active",
        "supports_js_render",
        "crawl_interval_minutes",
        "default_max_pages",
        "schedule_enabled",
        "schedule_days",
        "last_scheduled_run_at",
        "next_scheduled_run_at",
        "last_schedule_status",
    ]:
        assert column in table.c


def test_crawl_job_retry_fields_and_type_constraint_exist() -> None:
    table = _table("crawl_job")
    assert "retry_of_job_id" in table.c
    for column in [
        "queued_at",
        "picked_at",
        "list_items_seen",
        "list_items_unique",
        "list_items_source_duplicates_skipped",
        "detail_pages_fetched",
        "records_inserted",
        "records_updated",
        "source_duplicates_suppressed",
        "heartbeat_at",
        "timeout_at",
        "lease_expires_at",
    ]:
        assert column in table.c
    checks = "\n".join(_check_sql("crawl_job"))
    assert "manual_retry" in checks
    active_index = _index("crawl_job", "uq_crawl_job_source_active")
    assert active_index.unique is True
    where_clause = active_index.dialect_options["sqlite"].get("where")
    if where_clause is None:
        where_clause = active_index.dialect_options["postgresql"].get("where")
    where_sql = str(where_clause) if where_clause is not None else ""
    assert "pending" in where_sql
    assert "running" in where_sql


def test_health_rule_config_fields_exist() -> None:
    table = _table("health_rule_config")
    for column in [
        "recent_error_warning_threshold",
        "recent_error_critical_threshold",
        "consecutive_failure_warning_threshold",
        "consecutive_failure_critical_threshold",
        "partial_warning_enabled",
    ]:
        assert column in table.c


def test_tender_notice_type_constraint_exists() -> None:
    checks = "\n".join(_check_sql("tender_notice"))
    assert "announcement" in checks
    assert "change" in checks
    assert "result" in checks


def test_notice_version_constraints_exist() -> None:
    unique_sets = _unique_sets("notice_version")
    assert ("notice_id", "version_no") in unique_sets
    assert ("notice_id", "content_hash") in unique_sets
    assert "dedup_key" in _table("notice_version").c


def test_tender_attachment_dedup_constraints_exist() -> None:
    assert ("source_site_id", "url_hash") in _unique_sets("tender_attachment")


def test_relationships_can_be_configured() -> None:
    configure_mappers()

    assert TenderNotice.__mapper__.relationships["versions"].mapper.class_ is NoticeVersion
    assert NoticeVersion.__mapper__.relationships["raw_document"].mapper.class_ is RawDocument
    assert TenderAttachment.__mapper__.relationships["notice"].mapper.class_ is TenderNotice
