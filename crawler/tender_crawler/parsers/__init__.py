"""Structured parsers for tender fields."""

from tender_crawler.parsers.anhui_ggzy_zfcg_parser import AnhuiGgzyZfcgParser
from tender_crawler.parsers.base import BaseNoticeParser, ParsedAttachment, ParsedNotice
from tender_crawler.parsers.ccgp_gov_cn_parser import CcgpGovCnParser
from tender_crawler.parsers.ccgp_hubei_parser import CcgpHubeiParser
from tender_crawler.parsers.ccgp_jiangsu_parser import CcgpJiangsuParser
from tender_crawler.parsers.example_source_parser import ExampleSourceParser
from tender_crawler.parsers.ggzy_gov_cn_deal_parser import GgzyGovCnDealListRecord, GgzyGovCnDealParser
from tender_crawler.parsers.ggzy_gov_cn_parser import GgzyGovCnParser

__all__ = [
    "BaseNoticeParser",
    "AnhuiGgzyZfcgParser",
    "CcgpGovCnParser",
    "CcgpHubeiParser",
    "CcgpJiangsuParser",
    "ParsedAttachment",
    "ParsedNotice",
    "ExampleSourceParser",
    "GgzyGovCnDealListRecord",
    "GgzyGovCnDealParser",
    "GgzyGovCnParser",
]
