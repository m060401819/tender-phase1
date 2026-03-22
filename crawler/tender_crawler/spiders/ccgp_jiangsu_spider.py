from __future__ import annotations

from tender_crawler.parsers import CcgpJiangsuParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider


class CcgpJiangsuSpider(BaseSourceSpider):
    """Placeholder spider for ccgp_jiangsu source."""

    name = "ccgp_jiangsu"
    source_code = "ccgp_jiangsu"
    allowed_domains = ["ccgp-jiangsu.gov.cn", "www.ccgp-jiangsu.gov.cn"]
    start_urls = ["https://www.ccgp-jiangsu.gov.cn/home/list"]
    parser_cls = CcgpJiangsuParser
