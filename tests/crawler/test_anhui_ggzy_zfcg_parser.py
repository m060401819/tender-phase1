from __future__ import annotations

from decimal import Decimal

from tender_crawler.parsers import AnhuiGgzyZfcgParser


def test_anhui_parser_extracts_core_fields() -> None:
    parser = AnhuiGgzyZfcgParser()

    detail_url = "https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123"
    list_page_url = "https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1"

    parsed = parser.parse_notice(
        detail_url=detail_url,
        list_page_url=list_page_url,
        list_item_title="【合肥】测试项目采购公告",
        detail_html="<html><head><title>Detail</title></head><body></body></html>",
        xmdj_html="""
        <table>
          <tr><th>项目编号</th><td>HF-2026-001</td><th>采购人名称</th><td>合肥市测试局</td></tr>
          <tr><th>采购项目地点</th><td>安徽省合肥市</td><th>预算金额</th><td>163.5万元</td></tr>
        </table>
        """,
        bulletin_html="""
        <div id=\"title\">测试项目采购公告</div>
        <div id=\"tsSpan\">2026-03-10 09:30</div>
        <div id=\"content\">
          <p>预算金额：163.5万元</p>
          <p>提交响应文件截止时间：2026年03月20日10点00分</p>
          <p>采购人信息 名称：合肥市测试局</p>
          <a href=\"/download/spec.pdf\">附件下载</a>
        </div>
        """,
    )

    assert parsed.title == "测试项目采购公告"
    assert parsed.source_site_name == "安徽省公共资源交易监管网"
    assert parsed.source_site_url == "https://ggzy.ah.gov.cn"
    assert parsed.list_page_url == list_page_url
    assert parsed.detail_page_url == detail_url
    assert parsed.notice_type == "announcement"
    assert parsed.external_id == "abc123"
    assert parsed.project_code == "HF-2026-001"
    assert parsed.issuer == "合肥市测试局"
    assert parsed.region == "安徽省合肥市"
    assert parsed.budget_amount == Decimal("1635000")
    assert parsed.published_at is not None
    assert parsed.deadline_at is not None
    assert parsed.content_text and "提交响应文件截止时间" in parsed.content_text
    assert parsed.attachments
    assert parsed.attachments[0].file_url.endswith("/download/spec.pdf")
    assert parsed.attachments[0].file_name == "spec.pdf"
    assert parsed.attachments[0].mime_type == "application/pdf"


def test_anhui_parser_infers_result_notice_type() -> None:
    parser = AnhuiGgzyZfcgParser()

    parsed = parser.parse_notice(
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=result-1",
        list_page_url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
        list_item_title="【芜湖】测试项目成交结果公告",
        detail_html="<html></html>",
        xmdj_html="""
        <table>
          <tr><th>采购项目名称</th><td>测试项目</td></tr>
        </table>
        """,
        bulletin_html="""
        <div id=\"title\">测试项目成交结果公告</div>
        <div id=\"content\"><p>结果公告正文</p></div>
        """,
    )

    assert parsed.notice_type == "result"


def test_anhui_parser_dedupes_attachment_urls_by_normalized_form() -> None:
    parser = AnhuiGgzyZfcgParser()

    parsed = parser.parse_notice(
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=attach-1",
        list_page_url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
        list_item_title="附件去重测试",
        detail_html="<html></html>",
        xmdj_html="<table><tr><th>采购项目名称</th><td>附件去重测试</td></tr></table>",
        bulletin_html="""
        <div id="title">附件去重测试公告</div>
        <div id="content">
          <a href="/download/spec.pdf?b=2&a=1#frag">附件1</a>
          <a href="/download/spec.pdf?a=1&b=2">附件2</a>
        </div>
        """,
    )

    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].file_url == "https://ggzy.ah.gov.cn/download/spec.pdf?a=1&b=2"
