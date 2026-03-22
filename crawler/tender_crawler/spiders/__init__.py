"""Source-isolated spider modules.

Rule: one spider per data source.
"""

from tender_crawler.spiders.base_source_spider import BaseSourceSpider
from tender_crawler.spiders.anhui_ggzy_zfcg_spider import AnhuiGgzyZfcgSpider
from tender_crawler.spiders.ccgp_gov_cn_spider import CcgpGovCnSpider
from tender_crawler.spiders.ccgp_hubei_spider import CcgpHubeiSpider
from tender_crawler.spiders.ccgp_jiangsu_spider import CcgpJiangsuSpider
from tender_crawler.spiders.example_source_spider import ExampleSourceSpider
from tender_crawler.spiders.ggzy_gov_cn_deal_spider import GgzyGovCnDealSpider
from tender_crawler.spiders.ggzy_gov_cn_spider import GgzyGovCnSpider

__all__ = [
    "BaseSourceSpider",
    "ExampleSourceSpider",
    "AnhuiGgzyZfcgSpider",
    "CcgpGovCnSpider",
    "GgzyGovCnSpider",
    "GgzyGovCnDealSpider",
    "CcgpHubeiSpider",
    "CcgpJiangsuSpider",
]
