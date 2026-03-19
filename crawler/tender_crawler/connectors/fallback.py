from __future__ import annotations

from dataclasses import dataclass

from tender_crawler.connectors.base import BaseHtmlConnector
from tender_crawler.connectors.playwright_connector import PlaywrightConnector


@dataclass(slots=True)
class FallbackResult:
    html: str
    renderer: str


class PlaywrightFallbackConnector:
    """Fallback strategy: use Scrapy HTML first, then Playwright when page body is empty."""

    def __init__(self, connector: BaseHtmlConnector | None = None, min_html_length: int = 120) -> None:
        self.connector = connector or PlaywrightConnector()
        self.min_html_length = min_html_length

    async def fetch_with_fallback(
        self,
        url: str,
        primary_html: str | None,
        timeout_ms: int = 30000,
    ) -> FallbackResult:
        if primary_html and len(primary_html.strip()) >= self.min_html_length:
            return FallbackResult(html=primary_html, renderer="scrapy")

        html = await self.connector.fetch_html(url=url, timeout_ms=timeout_ms)
        return FallbackResult(html=html, renderer="playwright")
