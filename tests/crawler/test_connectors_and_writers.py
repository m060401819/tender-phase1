from __future__ import annotations

import asyncio

from tender_crawler.connectors.base import BaseHtmlConnector
from tender_crawler.connectors.fallback import PlaywrightFallbackConnector
from tender_crawler.writers.base import NoopErrorWriter, NoopNoticeWriter, NoopRawDocumentWriter
from tender_crawler.writers.factory import build_writer_bundle


class _FakeConnector(BaseHtmlConnector):
    async def fetch_html(self, url: str, timeout_ms: int = 30000) -> str:
        _ = timeout_ms
        return f"<html><body>rendered:{url}</body></html>"


def test_playwright_fallback_uses_primary_html_when_available() -> None:
    fallback = PlaywrightFallbackConnector(connector=_FakeConnector(), min_html_length=10)

    result = asyncio.run(
        fallback.fetch_with_fallback(
            url="https://example.com/test",
            primary_html="<html><body>primary</body></html>",
        )
    )

    assert result.renderer == "scrapy"
    assert "primary" in result.html


def test_playwright_fallback_uses_connector_when_primary_empty() -> None:
    fallback = PlaywrightFallbackConnector(connector=_FakeConnector(), min_html_length=10)

    result = asyncio.run(
        fallback.fetch_with_fallback(
            url="https://example.com/test",
            primary_html="",
        )
    )

    assert result.renderer == "playwright"
    assert "rendered:https://example.com/test" in result.html


def test_writer_factory_can_build_noop_bundle() -> None:
    bundle = build_writer_bundle({"CRAWLER_WRITER_BACKEND": "noop"})

    assert isinstance(bundle.raw_document_writer, NoopRawDocumentWriter)
    assert isinstance(bundle.notice_writer, NoopNoticeWriter)
    assert isinstance(bundle.error_writer, NoopErrorWriter)


def test_writer_factory_can_build_sqlalchemy_bundle(tmp_path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'factory_writer.db'}"
    bundle = build_writer_bundle(
        {
            "CRAWLER_WRITER_BACKEND": "sqlalchemy",
            "CRAWLER_DATABASE_URL": db_url,
        }
    )

    assert bundle.raw_document_writer.__class__.__name__ == "SqlAlchemyRawDocumentWriter"
    assert bundle.notice_writer.__class__.__name__ == "SqlAlchemyNoticeWriter"
    assert bundle.error_writer.__class__.__name__ == "SqlAlchemyErrorWriter"
    bundle.close()
