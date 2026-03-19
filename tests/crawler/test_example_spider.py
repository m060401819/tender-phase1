from __future__ import annotations

from itemadapter import ItemAdapter
from scrapy.http import Request, TextResponse

from tender_crawler.items import (
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_ATTACHMENT,
    ITEM_TYPE_TENDER_NOTICE,
)
from tender_crawler.spiders.example_source_spider import ExampleSourceSpider


def _build_response(url: str, body: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body.encode("utf-8"), encoding="utf-8")


def test_example_spider_emits_core_item_types() -> None:
    spider = ExampleSourceSpider()
    response = _build_response(
        url="https://example.com/notices/123",
        body="""
        <html>
          <head><title>Example Tender Notice</title></head>
          <body>
            <p>Sample notice for framework verification.</p>
            <a href="/download/notice.pdf">Download PDF</a>
          </body>
        </html>
        """,
    )

    emitted = list(spider.parse(response))
    item_types = {ItemAdapter(item).get("item_type") for item in emitted}

    assert ITEM_TYPE_RAW_DOCUMENT in item_types
    assert ITEM_TYPE_TENDER_NOTICE in item_types
    assert ITEM_TYPE_NOTICE_VERSION in item_types
    assert ITEM_TYPE_TENDER_ATTACHMENT in item_types

    notice = next(item for item in emitted if ItemAdapter(item).get("item_type") == ITEM_TYPE_TENDER_NOTICE)
    adapter = ItemAdapter(notice)
    assert adapter.get("title") == "Example Tender Notice"
    assert adapter.get("notice_type") == "announcement"
    assert adapter.get("source_code") == "example_source"
