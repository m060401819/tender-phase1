"""Connectors for dynamic pages and external source access."""

from tender_crawler.connectors.base import BaseHtmlConnector
from tender_crawler.connectors.fallback import FallbackResult, PlaywrightFallbackConnector
from tender_crawler.connectors.playwright_connector import PlaywrightConnector

__all__ = [
    "BaseHtmlConnector",
    "PlaywrightConnector",
    "PlaywrightFallbackConnector",
    "FallbackResult",
]
