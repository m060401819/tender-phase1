from __future__ import annotations

from tender_crawler.parsers import ExampleSourceParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider


class ExampleSourceSpider(BaseSourceSpider):
    """Runnable sample spider for framework verification."""

    name = "example_source"
    source_code = "example_source"
    allowed_domains = ["example.com"]
    start_urls = ["https://example.com/"]
    parser_cls = ExampleSourceParser
