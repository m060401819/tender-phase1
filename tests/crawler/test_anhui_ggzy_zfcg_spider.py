from __future__ import annotations

from urllib.parse import parse_qs

from itemadapter import ItemAdapter
from scrapy import FormRequest
from scrapy.http import Request, TextResponse

from tender_crawler.items import (
    ITEM_TYPE_CRAWL_ERROR,
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_ATTACHMENT,
    ITEM_TYPE_TENDER_NOTICE,
)
from tender_crawler.spiders.anhui_ggzy_zfcg_spider import AnhuiGgzyZfcgSpider


def _build_response(url: str, body: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body.encode("utf-8"), encoding="utf-8")


def test_anhui_spider_runs_list_detail_sub_chain() -> None:
    spider = AnhuiGgzyZfcgSpider(max_pages=1)

    list_response = _build_response(
        url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
        body="""
        <html>
          <body>
            <input id=\"currentPage\" value=\"1\" />
            <a href=\"/zfcg/newDetail?guid=abc123\">【合肥】测试项目采购公告</a>
          </body>
        </html>
        """,
    )

    list_emitted = list(spider.parse(list_response))
    assert any(ItemAdapter(item).get("item_type") == ITEM_TYPE_RAW_DOCUMENT for item in list_emitted if not isinstance(item, Request))

    detail_request = next(x for x in list_emitted if isinstance(x, Request))
    assert detail_request.url.endswith("guid=abc123")

    detail_response = _build_response(
        url=detail_request.url,
        body="<html><head><title>detail</title></head><body>detail page</body></html>",
    )
    detail_emitted = list(
        spider.parse_detail(
            detail_response,
            list_page_url=list_response.url,
            list_item_title="【合肥】测试项目采购公告",
        )
    )

    assert any(ItemAdapter(item).get("item_type") == ITEM_TYPE_RAW_DOCUMENT for item in detail_emitted if not isinstance(item, Request))
    xmdj_request = next(x for x in detail_emitted if isinstance(x, FormRequest))
    xmdj_form = parse_qs(xmdj_request.body.decode("utf-8"))
    assert xmdj_form["type"] == ["xmdj"]

    xmdj_response = _build_response(
        url=xmdj_request.url,
        body="""
        <table>
          <tr><th>项目编号</th><td>HF-2026-001</td><th>采购人名称</th><td>合肥市测试局</td></tr>
          <tr><th>采购项目地点</th><td>安徽省合肥市</td><th>预算金额</th><td>163.5万元</td></tr>
        </table>
        """,
    )
    xmdj_emitted = list(
        spider.parse_xmdj(
            xmdj_response,
            guid="abc123",
            detail_url=detail_response.url,
            detail_html=detail_response.text,
            list_page_url=list_response.url,
            list_item_title="【合肥】测试项目采购公告",
        )
    )

    assert any(ItemAdapter(item).get("item_type") == ITEM_TYPE_RAW_DOCUMENT for item in xmdj_emitted if not isinstance(item, Request))
    bulletin_request = next(x for x in xmdj_emitted if isinstance(x, FormRequest))
    bulletin_form = parse_qs(bulletin_request.body.decode("utf-8"))
    assert bulletin_form["type"] == ["bulletin"]

    bulletin_response = _build_response(
        url=bulletin_request.url,
        body="""
        <div id=\"title\">测试项目采购公告</div>
        <div id=\"tsSpan\">2026-03-10 09:30</div>
        <div id=\"content\">
          <p>预算金额：163.5万元</p>
          <p>提交响应文件截止时间：2026年03月20日10点00分</p>
          <a href=\"/download/spec.pdf\">附件下载</a>
        </div>
        """,
    )
    final_items = list(
        spider.parse_bulletin(
            bulletin_response,
            guid="abc123",
            detail_url=detail_response.url,
            detail_html=detail_response.text,
            xmdj_html=xmdj_response.text,
            list_page_url=list_response.url,
            list_item_title="【合肥】测试项目采购公告",
        )
    )

    item_types = {ItemAdapter(item).get("item_type") for item in final_items}
    assert ITEM_TYPE_RAW_DOCUMENT in item_types
    assert ITEM_TYPE_TENDER_NOTICE in item_types
    assert ITEM_TYPE_NOTICE_VERSION in item_types
    assert ITEM_TYPE_TENDER_ATTACHMENT in item_types

    notice_item = next(item for item in final_items if ItemAdapter(item).get("item_type") == ITEM_TYPE_TENDER_NOTICE)
    notice = ItemAdapter(notice_item)
    assert notice.get("title") == "测试项目采购公告"
    assert notice.get("source_code") == "anhui_ggzy_zfcg"
    assert notice.get("detail_page_url") == detail_response.url
    assert notice.get("list_page_url") == list_response.url


def test_anhui_spider_emits_crawl_error_when_guid_missing() -> None:
    spider = AnhuiGgzyZfcgSpider(max_pages=1)
    detail_response = _build_response(
        url="https://ggzy.ah.gov.cn/zfcg/newDetail",
        body="<html></html>",
    )

    emitted = list(
        spider.parse_detail(
            detail_response,
            list_page_url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
            list_item_title="测试标题",
        )
    )

    assert len(emitted) == 1
    error = ItemAdapter(emitted[0])
    assert error.get("item_type") == ITEM_TYPE_CRAWL_ERROR
    assert error.get("error_type") == "MissingGuid"
