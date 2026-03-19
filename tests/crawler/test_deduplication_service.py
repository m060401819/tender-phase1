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
