from playwright.async_api import async_playwright


class PlaywrightConnector:
    """Minimal Playwright connector reserved for JS-rendered tender pages."""

    async def fetch_html(self, url: str, timeout_ms: int = 30000) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=timeout_ms)
            html = await page.content()
            await browser.close()
            return html
