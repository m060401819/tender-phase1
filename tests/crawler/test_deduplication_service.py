from __future__ import annotations

from tender_crawler.services import DeduplicationService


def test_service_normalizes_url_and_hash() -> None:
    service = DeduplicationService()
    normalized_a, hash_a = service.normalize_url_and_hash(
        url="https://example.com/path?b=2&a=1#x",
    )
    normalized_b, hash_b = service.normalize_url_and_hash(
        url="https://example.com/path?a=1&b=2",
    )

    assert normalized_a == "https://example.com/path?a=1&b=2"
    assert normalized_a == normalized_b
    assert hash_a == hash_b


def test_service_builds_notice_identity_with_merge_priority() -> None:
    service = DeduplicationService()

    by_external = service.build_notice_identity(
        {
            "source_code": "src",
            "external_id": "N-1",
            "detail_page_url": "https://example.com/detail?id=1",
            "title": "公告A",
        }
    )
    by_detail = service.build_notice_identity(
        {
            "source_code": "src",
            "detail_page_url": "https://example.com/detail?id=1",
            "title": "公告A",
        }
    )
    by_title = service.build_notice_identity(
        {
            "source_code": "src",
            "title": "公告A",
        }
    )

    assert by_external.merge_strategy == "external_id"
    assert by_detail.merge_strategy == "detail_url"
    assert by_title.merge_strategy == "title"
    assert by_external.dedup_hash != by_detail.dedup_hash


def test_service_normalizes_notice_type() -> None:
    service = DeduplicationService()

    assert service.normalize_notice_type("result") == "result"
    assert service.normalize_notice_type("unknown") == "announcement"


def test_service_builds_source_list_fingerprint_with_normalization() -> None:
    service = DeduplicationService()

    fp_a = service.build_source_list_item_fingerprint(
        source_code="anhui_ggzy_zfcg",
        title="  测试　公告（一期）  ",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123&utm_source=xx&spm=123",
        published_at="2026年03月20日",
        notice_type="announcement",
        region=" 合肥 ",
    )
    fp_b = service.build_source_list_item_fingerprint(
        source_code="anhui_ggzy_zfcg",
        title="测试 公告(一期)",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
        published_at="2026-03-20",
        notice_type="announcement",
        region="合肥",
    )

    assert fp_a == fp_b


def test_service_builds_source_duplicate_key_by_notice_identity_fields() -> None:
    service = DeduplicationService()

    key_a = service.build_source_duplicate_key(
        source_code="anhui_ggzy_zfcg",
        title="低压透明化改造项目公告",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123&from=home",
        published_at="2026-03-20 10:00:00",
        notice_type="announcement",
        region="合肥",
    )
    key_b = service.build_source_duplicate_key(
        source_code="anhui_ggzy_zfcg",
        title=" 低压透明化改造项目公告 ",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
        published_at="2026年03月20日10点00分",
        notice_type="announcement",
        region=" 合肥 ",
    )

    assert key_a == key_b


def test_service_builds_source_duplicate_key_prefers_detail_locator_even_when_title_changes() -> None:
    service = DeduplicationService()

    key_a = service.build_source_duplicate_key(
        source_code="anhui_ggzy_zfcg",
        title="低压透明化改造项目公告（第一次抓取）",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
        published_at="2026-03-20",
        notice_type="announcement",
        region="合肥",
    )
    key_b = service.build_source_duplicate_key(
        source_code="anhui_ggzy_zfcg",
        title="低压透明化改造项目公告（标题微调）",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123&from=list",
        published_at="2026-03-20",
        notice_type="announcement",
        region="合肥",
    )

    assert key_a == key_b


def test_service_builds_dedup_key_with_budget_bucket_and_detail_locator() -> None:
    service = DeduplicationService()

    key_a = service.build_notice_dedup_key(
        title="低压 透明化 改造项目（一期）",
        published_at="2026-03-20 09:00:00",
        purchaser="安徽电力公司",
        budget_amount="1001499",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123&utm_source=xx",
    )
    key_b = service.build_notice_dedup_key(
        title="低压透明化改造项目(一期)",
        published_at="2026年03月20日",
        publisher=" 安徽电力 公司 ",
        budget_amount="1001201",
        detail_url="https://ggzy.ah.gov.cn/zfcg/newDetail?guid=abc123",
    )

    assert key_a == key_b


def test_service_builds_persistence_dedup_key_for_business_similarity() -> None:
    service = DeduplicationService()

    key_a = service.build_persistence_dedup_key(
        title="低压 透明化 改造项目（一期）",
        published_at="2026-03-20 09:00:00",
        publisher="安徽电力公司",
        budget_amount="1001499",
        region=" 合肥 ",
    )
    key_b = service.build_persistence_dedup_key(
        title="低压透明化改造项目(一期)",
        published_at="2026年03月20日",
        publisher=" 安徽电力 公司 ",
        budget_amount="1001201",
        region="合肥",
    )

    assert key_a == key_b


def test_extract_detail_locator_prefers_guid_or_detail_id() -> None:
    service = DeduplicationService()

    locator_guid = service.extract_detail_locator(
        detail_url="https://example.com/detail?guid=G-001&id=99",
    )
    locator_id = service.extract_detail_locator(
        detail_url="https://example.com/detail?detail_id=DX-9",
    )
    locator_url = service.extract_detail_locator(
        detail_url="https://example.com/detail?a=1&b=2",
    )

    assert locator_guid == "g-001"
    assert locator_id == "dx-9"
    assert locator_url == "https://example.com/detail?a=1&b=2"
