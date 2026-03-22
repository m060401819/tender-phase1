from __future__ import annotations

from tender_crawler.parsers import GgzyGovCnParser
from tender_crawler.spiders.base_source_spider import BaseSourceSpider


class GgzyGovCnSpider(BaseSourceSpider):
    """Placeholder spider for ggzy_gov_cn source."""

    name = "ggzy_gov_cn"
    source_code = "ggzy_gov_cn"
    allowed_domains = ["ggzy.gov.cn", "www.ggzy.gov.cn"]
    start_urls = ["https://www.ggzy.gov.cn/information/html/a/0901/index.shtml"]
    parser_cls = GgzyGovCnParser
