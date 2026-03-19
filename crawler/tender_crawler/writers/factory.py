from __future__ import annotations

from typing import Any

from tender_crawler.writers.base import (
    NoopErrorWriter,
    NoopNoticeWriter,
    NoopRawDocumentWriter,
    WriterBundle,
)
from tender_crawler.writers.error_writer import JsonlErrorWriter
from tender_crawler.writers.notice_writer import JsonlNoticeWriter
from tender_crawler.writers.raw_document_writer import JsonlRawDocumentWriter


def build_writer_bundle(settings: Any) -> WriterBundle:
    """Build writers by backend mode.

    `jsonl`: write staged payloads to local JSONL files.
    `sqlalchemy`: write to phase-1 PostgreSQL tables via SQLAlchemy.
    `noop`: keep data in-memory flow only.
    """

    backend = str(settings.get("CRAWLER_WRITER_BACKEND", "jsonl")).lower()
    output_dir = str(settings.get("CRAWLER_WRITER_OUTPUT_DIR", "data/staging"))

    if backend == "noop":
        return WriterBundle(
            raw_document_writer=NoopRawDocumentWriter(),
            notice_writer=NoopNoticeWriter(),
            error_writer=NoopErrorWriter(),
        )

    if backend == "jsonl":
        return WriterBundle(
            raw_document_writer=JsonlRawDocumentWriter(output_dir=output_dir),
            notice_writer=JsonlNoticeWriter(output_dir=output_dir),
            error_writer=JsonlErrorWriter(output_dir=output_dir),
        )

    if backend == "sqlalchemy":
        from tender_crawler.writers.sqlalchemy_writer import (
            SqlAlchemyErrorWriter,
            SqlAlchemyNoticeWriter,
            SqlAlchemyRawDocumentWriter,
            SqlAlchemyWriterContext,
            resolve_database_url,
        )

        context = SqlAlchemyWriterContext(database_url=resolve_database_url(settings))
        return WriterBundle(
            raw_document_writer=SqlAlchemyRawDocumentWriter(context=context),
            notice_writer=SqlAlchemyNoticeWriter(context=context),
            error_writer=SqlAlchemyErrorWriter(context=context),
        )

    raise ValueError(f"Unsupported CRAWLER_WRITER_BACKEND: {backend}")
