from __future__ import annotations

from playwright.async_api import async_playwright

from tender_crawler.connectors.base import BaseHtmlConnector


class PlaywrightConnector(BaseHtmlConnector):
    """Playwright connector for JS-rendered pages."""

    async def fetch_html(self, url: str, timeout_ms: int = 30000) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            html = await page.content()
            await browser.close()
            return html
