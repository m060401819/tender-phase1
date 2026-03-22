from __future__ import annotations

import json

from itemadapter import ItemAdapter
from scrapy import FormRequest
from scrapy.http import Request, TextResponse

from tender_crawler.items import (
    ITEM_TYPE_CRAWL_ERROR,
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_NOTICE,
)
from tender_crawler.spiders.ggzy_gov_cn_deal_spider import GgzyGovCnDealSpider


def _build_response(url: str, body: str, *, content_type: str = "text/html; charset=utf-8") -> TextResponse:
    request = Request(url=url)
    return TextResponse(
        url=url,
        request=request,
        body=body.encode("utf-8"),
        encoding="utf-8",
        headers={"Content-Type": content_type},
    )


def test_ggzy_spider_landing_and_list_flow_with_run_dedup() -> None:
    spider = GgzyGovCnDealSpider(max_pages=3, job_type="manual")

    landing = _build_response(
        "https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
        "<html><head><title>交易公开</title></head><body></body></html>",
    )
    landing_items = list(spider.parse_landing(landing))
    assert any(
        ItemAdapter(item).get("item_type") == ITEM_TYPE_RAW_DOCUMENT
        for item in landing_items
        if not isinstance(item, Request)
    )
    first_list_request = next(item for item in landing_items if isinstance(item, FormRequest))
    assert first_list_request.url.endswith("/information/pubTradingInfo/getTradList")

    list_payload = {
        "code": 200,
        "message": "success",
        "data": {
            "records": [
                {
                    "title": "某市低压透明化改造采购公告",
                    "publishTime": "2026-03-21",
                    "provinceText": "安徽",
                    "transactionSourcesPlatformText": "合肥市公共资源交易中心",
                    "informationTypeText": "采购/资审公告",
                    "url": "/deal/a.html",
                },
                {
                    "title": "某市低压透明化改造采购公告",
                    "publishTime": "2026-03-21",
                    "provinceText": "安徽",
                    "transactionSourcesPlatformText": "合肥市公共资源交易中心",
                    "informationTypeText": "采购/资审公告",
                    "url": "/deal/a.html",
                },
            ],
            "total": 2,
            "pages": 1,
            "current": 1,
        },
    }
    list_response = _build_response(
        spider.list_api_url,
        json.dumps(list_payload, ensure_ascii=False),
        content_type="application/json",
    )

    list_items = list(
        spider.parse_list_page(
            list_response,
            page=1,
            list_page_url="https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
        )
    )

    item_types = [
        ItemAdapter(item).get("item_type")
        for item in list_items
        if not isinstance(item, Request)
    ]
    assert ITEM_TYPE_RAW_DOCUMENT in item_types
    assert ITEM_TYPE_TENDER_NOTICE in item_types
    assert ITEM_TYPE_NOTICE_VERSION in item_types

    detail_requests = [item for item in list_items if isinstance(item, Request)]
    assert len(detail_requests) == 1
    assert detail_requests[0].url == "https://www.ggzy.gov.cn/deal/a.html"

    list_raw = next(
        item
        for item in list_items
        if not isinstance(item, Request) and ItemAdapter(item).get("item_type") == ITEM_TYPE_RAW_DOCUMENT
    )
    list_meta = ItemAdapter(list_raw).get("extra_meta")
    assert list_meta["page_item_count"] == 2
    assert list_meta["new_unique_item_count"] == 1
    assert list_meta["page_source_duplicates_skipped"] == 1


def test_ggzy_spider_reports_captcha_error() -> None:
    spider = GgzyGovCnDealSpider(max_pages=1, job_type="manual")
    payload = {
        "code": 829,
        "message": "captcha required",
        "data": {
            "records": [],
            "total": 0,
            "pages": 0,
            "current": 1,
        },
    }
    response = _build_response(
        spider.list_api_url,
        json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
    )

    emitted = list(
        spider.parse_list_page(
            response,
            page=1,
            list_page_url="https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
        )
    )

    error_items = [
        ItemAdapter(item)
        for item in emitted
        if not isinstance(item, Request) and ItemAdapter(item).get("item_type") == ITEM_TYPE_CRAWL_ERROR
    ]
    assert error_items
    assert "验证码" in (error_items[0].get("error_message") or "")
