from __future__ import annotations

from scrapy.http import Response

from tender_crawler.parsers.base import BaseNoticeParser, ParsedNotice


class ExampleSourceParser(BaseNoticeParser):
    """Parser for sample source to demonstrate parser extension points."""

    def parse(self, response: Response) -> ParsedNotice:
        notice = super().parse(response)
        notice.notice_type = "announcement"
        notice.region = "示例区域"
        notice.issuer = "示例招标人"
        if not notice.summary:
            notice.summary = "示例站点公告（占位）。"
        return notice
