from __future__ import annotations

from scrapy.http import Request, TextResponse

from tender_crawler.parsers.base import BaseNoticeParser


def _build_response(url: str, body: str) -> TextResponse:
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=body.encode("utf-8"), encoding="utf-8")


def test_base_parser_extracts_title_summary_and_attachments() -> None:
    response = _build_response(
        url="https://example.com/notices/1",
        body="""
        <html>
          <head><title>示例招标公告</title></head>
          <body>
            <p>这是一个用于测试的公告摘要。</p>
            <a href="/files/spec.pdf">招标文件</a>
            <a href="/about">关于我们</a>
          </body>
        </html>
        """,
    )

    parser = BaseNoticeParser()
    parsed = parser.parse(response)

    assert parsed.title == "示例招标公告"
    assert parsed.notice_type == "announcement"
    assert parsed.summary == "这是一个用于测试的公告摘要。"
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].file_url == "https://example.com/files/spec.pdf"
