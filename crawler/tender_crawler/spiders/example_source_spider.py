from datetime import datetime, timezone

import scrapy

from tender_crawler.parsers.base import BaseTenderParser


class ExampleSourceSpider(scrapy.Spider):
    name = "example_source"
    allowed_domains = ["example.com"]
    start_urls = ["https://example.com/"]

    parser = BaseTenderParser()

    def parse(self, response: scrapy.http.Response):
        yield {
            "source": self.name,
            "url": response.url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "raw_html": response.text,
            "normalized": self.parser.parse(response.text),
        }
