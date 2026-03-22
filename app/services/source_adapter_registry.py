from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceAdapterMeta:
    source_code: str
    spider_name: str
    business_code: str
    display_name: str
    base_url: str
    official_url: str
    list_url: str
    supported_job_types: tuple[str, ...]


_INTEGRATED_ADAPTERS: dict[str, SourceAdapterMeta] = {
    "example_source": SourceAdapterMeta(
        source_code="example_source",
        spider_name="example_source",
        business_code="example_source",
        display_name="示例来源",
        base_url="https://example.com/",
        official_url="https://example.com/",
        list_url="https://example.com/notices",
        supported_job_types=("manual", "manual_retry", "backfill"),
    ),
    "anhui_ggzy_zfcg": SourceAdapterMeta(
        source_code="anhui_ggzy_zfcg",
        spider_name="anhui_ggzy_zfcg",
        business_code="anhui_ggzy_zfcg",
        display_name="安徽省公共资源交易监管网（政府采购）",
        base_url="https://ggzy.ah.gov.cn/",
        official_url="https://ggzy.ah.gov.cn/",
        list_url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
        supported_job_types=("manual", "manual_retry", "backfill"),
    ),
    "ggzy_gov_cn_deal": SourceAdapterMeta(
        source_code="ggzy_gov_cn_deal",
        spider_name="ggzy_gov_cn_deal",
        business_code="ggzy_gov_cn_deal",
        display_name="全国公共资源交易平台（政府采购）",
        base_url="https://www.ggzy.gov.cn/",
        official_url="https://www.ggzy.gov.cn/",
        list_url="https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
        supported_job_types=("manual", "manual_retry", "backfill"),
    ),
}

_LEGACY_SOURCE_CODE_ALIASES = {
    "2": "ggzy_gov_cn_deal",
    "ggzy_gov_cn": "ggzy_gov_cn_deal",
}


def normalize_source_code(source_code: str) -> str:
    normalized = source_code.strip()
    if not normalized:
        return normalized
    return _LEGACY_SOURCE_CODE_ALIASES.get(normalized, normalized)


def get_source_adapter(source_code: str) -> SourceAdapterMeta | None:
    normalized = normalize_source_code(source_code)
    return _INTEGRATED_ADAPTERS.get(normalized)


def is_source_integrated(source_code: str) -> bool:
    return get_source_adapter(source_code) is not None


def resolve_spider_name(source_code: str) -> str | None:
    adapter = get_source_adapter(source_code)
    if adapter is None:
        return None
    return adapter.spider_name


def supports_job_type(source_code: str, *, job_type: str) -> bool:
    adapter = get_source_adapter(source_code)
    if adapter is None:
        return False
    return job_type in adapter.supported_job_types


def list_integrated_source_codes() -> list[str]:
    return sorted(_INTEGRATED_ADAPTERS.keys())
