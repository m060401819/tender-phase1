from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urljoin, urlsplit

from parsel import Selector

from tender_crawler.parsers.base import BaseNoticeParser, ParsedAttachment, ParsedNotice
from tender_crawler.utils import normalize_url


class AnhuiGgzyZfcgParser(BaseNoticeParser):
    """Parser for Anhui public resources government procurement notices."""

    source_site_name = "安徽省公共资源交易监管网"
    source_site_url = "https://ggzy.ah.gov.cn"

    def parse_notice(
        self,
        *,
        detail_url: str,
        list_page_url: str,
        list_item_title: str,
        list_item_published_at: str | None = None,
        detail_html: str,
        xmdj_html: str,
        bulletin_html: str,
    ) -> ParsedNotice:
        xmdj_sel = Selector(text=xmdj_html)
        bulletin_sel = Selector(text=bulletin_html)

        xmdj_map = self._table_kv_map(xmdj_sel)

        title = self._clean_text(
            bulletin_sel.css("#title::text").get()
            or xmdj_map.get("采购项目名称")
            or list_item_title
            or detail_url
        )

        body_text = self._extract_bulletin_body_text(bulletin_html)
        published_at = self._parse_datetime(
            self._clean_text(bulletin_sel.css("#tsSpan::text").get())
        ) or self._parse_datetime(list_item_published_at)
        deadline_at = self._extract_deadline(body_text)

        budget_amount = self._extract_budget_amount(body_text, xmdj_map)
        issuer = self._extract_issuer(body_text, xmdj_map)
        region = self._extract_region(list_item_title=list_item_title, xmdj_map=xmdj_map)

        external_id = self._extract_guid(detail_url)
        project_code = xmdj_map.get("项目编号")
        notice_type = self._infer_notice_type(title)
        attachments = self._extract_attachments(bulletin_sel, detail_url)

        summary = body_text[:2000] if body_text else None

        structured_data = {
            "source_site_name": self.source_site_name,
            "source_site_url": self.source_site_url,
            "list_page_url": list_page_url,
            "detail_page_url": detail_url,
            "list_item_title": list_item_title,
            "xmdj_fields": xmdj_map,
            "bulletin_time_raw": self._clean_text(bulletin_sel.css("#tsSpan::text").get()),
            "original_link": bulletin_sel.css("#link::attr(href)").get(),
            "content_text": body_text,
        }

        return ParsedNotice(
            title=title,
            notice_type=notice_type,
            external_id=external_id,
            project_code=project_code,
            issuer=issuer,
            region=region,
            published_at=published_at,
            deadline_at=deadline_at,
            budget_amount=budget_amount,
            budget_currency="CNY",
            summary=summary,
            content_text=body_text,
            source_site_name=self.source_site_name,
            source_site_url=self.source_site_url,
            list_page_url=list_page_url,
            detail_page_url=detail_url,
            structured_data=structured_data,
            attachments=attachments,
        )

    def _table_kv_map(self, selector: Selector) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for tr in selector.css("tr"):
            cells = [self._clean_text(x) for x in tr.css("th::text,td::text").getall() if self._clean_text(x)]
            if not cells:
                continue

            idx = 0
            while idx + 1 < len(cells):
                key = cells[idx]
                value = cells[idx + 1]
                if key and value:
                    pairs[key] = value
                idx += 2
        return pairs

    def _extract_bulletin_body_text(self, bulletin_html: str) -> str:
        html = re.sub(r"<style[\\s\\S]*?</style>", " ", bulletin_html, flags=re.IGNORECASE)
        html = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)

        selector = Selector(text=html)
        texts = [self._clean_text(x) for x in selector.css("#content *::text").getall() if self._clean_text(x)]
        body = "\n".join(texts)
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body.strip()

    def _extract_deadline(self, body_text: str) -> datetime | None:
        patterns = [
            r"(?:提交(?:响应|投标)文件截止时间|截止时间)[:：\s]*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日[0-9]{1,2}点[0-9]{1,2}分)",
            r"(?:提交(?:响应|投标)文件截止时间|截止时间)[:：\s]*([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}\s*[0-9]{1,2}:[0-9]{2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text)
            if match:
                dt = self._parse_datetime(match.group(1))
                if dt is not None:
                    return dt
        return None

    def _extract_budget_amount(self, body_text: str, xmdj_map: dict[str, str]) -> Decimal | None:
        match = re.search(r"预算金额[:：]\s*([0-9][0-9,\\.]*)(?:\s*(万元|元))?", body_text)
        if match:
            value = self._parse_decimal(match.group(1))
            if value is not None:
                unit = match.group(2) or ""
                if "万" in unit:
                    return value * Decimal("10000")
                return value

        xmdj_raw = xmdj_map.get("预算金额", "")
        value = self._parse_decimal(xmdj_raw)
        if value is not None:
            if "万" in xmdj_raw:
                return value * Decimal("10000")
            return value
        return None

    def _extract_issuer(self, body_text: str, xmdj_map: dict[str, str]) -> str | None:
        issuer = xmdj_map.get("采购人名称")
        if issuer:
            return issuer

        match = re.search(r"采购人(?:信息)?[\s\S]{0,120}?名称[:：]\s*([^\n\r]+)", body_text)
        if match:
            return self._clean_text(match.group(1))
        return None

    def _extract_region(self, *, list_item_title: str, xmdj_map: dict[str, str]) -> str | None:
        region = xmdj_map.get("采购项目地点")
        if region:
            return region

        list_title = self._clean_text(list_item_title)
        match = re.search(r"【([^】]+)】", list_title)
        if match:
            part = self._clean_text(match.group(1))
            if part:
                return part
        return None

    def _extract_attachments(self, selector: Selector, detail_url: str) -> list[ParsedAttachment]:
        attachments: list[ParsedAttachment] = []
        seen: set[str] = set()

        for anchor in selector.css("a[href]"):
            href = (anchor.attrib.get("href") or "").strip()
            text = self._clean_text(" ".join(anchor.css("::text").getall()))
            if not href:
                continue

            file_url = urljoin(detail_url, href)
            lowered = file_url.lower()

            is_file = lowered.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"))
            looks_attachment = "附件" in text or "下载" in text
            if not is_file and not looks_attachment:
                continue

            normalized_url = normalize_url(file_url)
            if normalized_url in seen:
                continue
            seen.add(normalized_url)

            attachment = self.build_attachment(
                file_url=file_url,
                base_url=detail_url,
                link_text=text,
                attachment_type="notice_file",
            )
            if attachment is None:
                continue
            attachments.append(attachment)

        return attachments

    def _extract_guid(self, detail_url: str) -> str | None:
        query = parse_qs(urlsplit(detail_url).query)
        guid = query.get("guid", [None])[0]
        if guid:
            return guid
        return None

    def _infer_notice_type(self, title: str) -> str:
        if any(key in title for key in ("更正", "变更", "澄清", "延期")):
            return "change"
        if any(key in title for key in ("中标", "成交", "结果", "中选")):
            return "result"
        return "announcement"

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None

        cleaned = self._clean_text(value)
        candidates = [
            "%Y%m%d",
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y年%m月%d日",
            "%Y年%m月%d日%H点%M分",
            "%Y年%m月%d日 %H点%M分",
        ]
        for fmt in candidates:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        date_match = re.search(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日([0-9]{1,2})点([0-9]{1,2})分", cleaned)
        if date_match:
            year, month, day, hour, minute = [int(x) for x in date_match.groups()]
            return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

        date_match = re.search(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日", cleaned)
        if date_match:
            year, month, day = [int(x) for x in date_match.groups()]
            return datetime(year, month, day, tzinfo=timezone.utc)

        return None

    def _parse_decimal(self, value: str | None) -> Decimal | None:
        if not value:
            return None
        normalized = value.replace(",", "").strip()
        match = re.search(r"[0-9]+(?:\.[0-9]+)?", normalized)
        if not match:
            return None
        try:
            return Decimal(match.group(0))
        except (InvalidOperation, ValueError):
            return None

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value).strip()
