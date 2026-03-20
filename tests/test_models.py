from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint
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


def test_phase1_core_tables_are_registered() -> None:
    expected = {
        "source_site",
        "crawl_job",
        "raw_document",
        "tender_notice",
        "tender_attachment",
        "notice_version",
        "crawl_error",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))


def test_raw_document_dedup_constraints_exist() -> None:
    assert ("source_site_id", "url_hash") in _unique_sets("raw_document")
    assert "content_hash" in _table("raw_document").c


def test_tender_notice_core_fields_exist() -> None:
    table = _table("tender_notice")
    for column in ["notice_type", "published_at", "deadline_at", "region", "issuer", "budget_amount"]:
        assert column in table.c


def test_source_site_runtime_config_fields_exist() -> None:
    table = _table("source_site")
    for column in ["is_active", "supports_js_render", "crawl_interval_minutes", "default_max_pages"]:
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


def test_tender_attachment_dedup_constraints_exist() -> None:
    assert ("source_site_id", "url_hash") in _unique_sets("tender_attachment")


def test_relationships_can_be_configured() -> None:
    configure_mappers()

    assert TenderNotice.__mapper__.relationships["versions"].mapper.class_ is NoticeVersion
    assert NoticeVersion.__mapper__.relationships["raw_document"].mapper.class_ is RawDocument
    assert TenderAttachment.__mapper__.relationships["notice"].mapper.class_ is TenderNotice
