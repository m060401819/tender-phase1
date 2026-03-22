from __future__ import annotations

from tender_crawler.parsers import CcgpHubeiParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider


class CcgpHubeiSpider(BaseSourceSpider):
    """Placeholder spider for ccgp_hubei source."""

    name = "ccgp_hubei"
    source_code = "ccgp_hubei"
    allowed_domains = ["ccgp-hubei.gov.cn", "www.ccgp-hubei.gov.cn"]
    start_urls = ["https://www.ccgp-hubei.gov.cn/notice.html"]
    parser_cls = CcgpHubeiParser
