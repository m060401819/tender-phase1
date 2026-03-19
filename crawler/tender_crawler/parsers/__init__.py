"""Structured parsers for tender fields."""

from tender_crawler.parsers.anhui_ggzy_zfcg_parser import AnhuiGgzyZfcgParser
from tender_crawler.parsers.base import BaseNoticeParser, ParsedAttachment, ParsedNotice
from tender_crawler.parsers.example_source_parser import ExampleSourceParser

__all__ = [
    "BaseNoticeParser",
    "AnhuiGgzyZfcgParser",
    "ParsedAttachment",
    "ParsedNotice",
    "ExampleSourceParser",
]
