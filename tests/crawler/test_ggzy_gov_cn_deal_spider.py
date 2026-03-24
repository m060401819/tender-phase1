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
    assert detail_requests[0].headers.get("Referer") == b"https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02"
    assert detail_requests[0].headers.get("User-Agent") == spider.browser_user_agent.encode()

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


def test_ggzy_spider_marks_json_detail_response_as_retryable_fetch_error() -> None:
    spider = GgzyGovCnDealSpider(max_pages=1, job_type="manual")
    list_page_url = "https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02"
    parsed_record = spider.parser.parse_list_record(
        record={
            "title": "某地低压透明化改造采购合同",
            "publishTime": "2026-03-20",
            "provinceText": "浙江省",
            "transactionSourcesPlatformText": "温州市公共资源交易网",
            "informationTypeText": "采购合同",
            "url": "/information/deal/html/a/330000/0203/20260320/example.html",
        },
        source_code=spider.source_code,
        list_page_url=list_page_url,
    )
    assert parsed_record is not None

    response = _build_response(
        "https://www.ggzy.gov.cn/information/deal/html/a/330000/0203/20260320/example.html",
        json.dumps({"code": 800, "message": "系统繁忙，请稍后再试!"}, ensure_ascii=False),
        content_type="application/json",
    )

    emitted = list(
        spider.parse_detail(
            response,
            list_page_url=list_page_url,
            record=spider._serialize_record(parsed_record),
        )
    )

    item_types = [ItemAdapter(item).get("item_type") for item in emitted]
    assert ITEM_TYPE_RAW_DOCUMENT in item_types
    assert ITEM_TYPE_CRAWL_ERROR in item_types
    assert ITEM_TYPE_TENDER_NOTICE not in item_types
    assert ITEM_TYPE_NOTICE_VERSION not in item_types

    error_item = next(
        ItemAdapter(item)
        for item in emitted
        if ItemAdapter(item).get("item_type") == ITEM_TYPE_CRAWL_ERROR
    )
    assert error_item.get("stage") == "fetch"
    assert error_item.get("retryable") is True
    assert error_item.get("error_message") == "详情获取失败: 详情页返回JSON code=800 message=系统繁忙，请稍后再试!"
