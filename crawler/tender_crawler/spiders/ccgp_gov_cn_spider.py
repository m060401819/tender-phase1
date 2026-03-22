from __future__ import annotations

from tender_crawler.parsers import CcgpGovCnParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider


class CcgpGovCnSpider(BaseSourceSpider):
    """Placeholder spider for ccgp_gov_cn source."""

    name = "ccgp_gov_cn"
    source_code = "ccgp_gov_cn"
    allowed_domains = ["ccgp.gov.cn", "www.ccgp.gov.cn"]
    start_urls = ["https://search.ccgp.gov.cn/bxsearch"]
    parser_cls = CcgpGovCnParser
