from __future__ import annotations

from scrapy.http import Request, TextResponse

from tender_crawler.parsers import GgzyGovCnDealParser


def _build_response(url: str, body: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body.encode("utf-8"), encoding="utf-8")


def test_ggzy_parser_extracts_required_list_fields() -> None:
    parser = GgzyGovCnDealParser()
    record = {
        "title": "某市负荷管理平台采购公告",
        "publishTime": "2026-03-20 09:31:00",
        "provinceText": "安徽",
        "transactionSourcesPlatformText": "合肥市公共资源交易中心",
        "informationTypeText": "采购/资审公告",
        "url": "/deal/001302e9a797f2c540118c795cb8db5c29f3.html",
    }

    parsed = parser.parse_list_record(
        record=record,
        source_code="ggzy_gov_cn_deal",
        list_page_url="https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
    )

    assert parsed is not None
    assert parsed.title == "某市负荷管理平台采购公告"
    assert parsed.published_at_iso == "2026-03-20T00:00:00+00:00"
    assert parsed.province == "安徽"
    assert parsed.source_platform == "合肥市公共资源交易中心"
    assert parsed.notice_type == "announcement"
    assert parsed.detail_url == "https://www.ggzy.gov.cn/deal/001302e9a797f2c540118c795cb8db5c29f3.html"
    assert parsed.source_duplicate_key
    assert parsed.source_list_item_fingerprint


def test_ggzy_parser_fallback_dedup_key_uses_normalized_title() -> None:
    parser = GgzyGovCnDealParser()
    list_url = "https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02"
    record_a = {
        "title": "ＡＢＣ 设备   采购公告",
        "publishTime": "2026-03-21",
        "provinceText": "安徽",
        "transactionSourcesPlatformText": "合肥市公共资源交易中心",
        "informationTypeText": "采购/资审公告",
        "url": "",
    }
    record_b = {
        "title": "ABC设备采购",
        "publishTime": "2026/03/21 10:00",
        "provinceText": "安徽",
        "transactionSourcesPlatformText": "合肥市公共资源交易中心",
        "informationTypeText": "采购/资审公告",
        "url": "",
    }

    parsed_a = parser.parse_list_record(record=record_a, source_code="ggzy_gov_cn_deal", list_page_url=list_url)
    parsed_b = parser.parse_list_record(record=record_b, source_code="ggzy_gov_cn_deal", list_page_url=list_url)

    assert parsed_a is not None
    assert parsed_b is not None
    assert parsed_a.normalized_detail_url is None
    assert parsed_b.normalized_detail_url is None
    assert parsed_a.source_duplicate_key == parsed_b.source_duplicate_key


def test_ggzy_parser_detail_extracts_text_and_attachments() -> None:
    parser = GgzyGovCnDealParser()
    list_url = "https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02"

    list_record = parser.parse_list_record(
        record={
            "title": "某地电力设备采购公告",
            "publishTime": "2026-03-20",
            "provinceText": "江苏",
            "transactionSourcesPlatformText": "某平台",
            "informationTypeText": "采购/资审公告",
            "url": "/deal/sample-detail.html",
        },
        source_code="ggzy_gov_cn_deal",
        list_page_url=list_url,
    )
    assert list_record is not None

    response = _build_response(
        url="https://www.ggzy.gov.cn/deal/sample-detail.html",
        body="""
        <html>
          <head><title>详情页标题</title></head>
          <body>
            <div class=\"content\">正文内容片段</div>
            <a href=\"/download/spec.pdf\">附件下载</a>
          </body>
        </html>
        """,
    )

    parsed_notice = parser.parse_detail_notice(
        response=response,
        list_record=list_record,
        list_page_url=list_url,
    )

    assert parsed_notice.title == "详情页标题"
    assert parsed_notice.content_text is not None and "正文内容片段" in parsed_notice.content_text
    assert parsed_notice.attachments
    assert parsed_notice.attachments[0].file_url == "https://www.ggzy.gov.cn/download/spec.pdf"
