"""Source-isolated spider modules.

Rule: one spider per data source.
"""

from tender_crawler.spiders.base_source_spider import BaseSourceSpider
from tender_crawler.spiders.example_source_spider import ExampleSourceSpider
from tender_crawler.spiders.anhui_ggzy_zfcg_spider import AnhuiGgzyZfcgSpider

__all__ = ["BaseSourceSpider", "ExampleSourceSpider", "AnhuiGgzyZfcgSpider"]
