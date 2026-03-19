from __future__ import annotations

from abc import ABC, abstractmethod


class BaseHtmlConnector(ABC):
    """Abstract connector for dynamic page rendering."""

    @abstractmethod
    async def fetch_html(self, url: str, timeout_ms: int = 30000) -> str:
        raise NotImplementedError
