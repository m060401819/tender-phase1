from __future__ import annotations

from app.repositories import SourceSiteRecord, SourceSiteRepository
from app.services.source_adapter_registry import normalize_source_code


class SourceSiteService:
    """Service layer for source_site queries."""

    def __init__(self, repository: SourceSiteRepository) -> None:
        self.repository = repository

    def list_sources(self) -> list[SourceSiteRecord]:
        return self.repository.list_sources()

    def get_source(self, code: str) -> SourceSiteRecord | None:
        normalized = code.strip()
        if not normalized:
            return None
        source = self.repository.get_by_code(normalized)
        if source is not None:
            return source
        alias_code = normalize_source_code(normalized)
        if alias_code and alias_code != normalized:
            return self.repository.get_by_code(alias_code)
        return None

    def update_source(self, code: str, updates: dict[str, object]) -> SourceSiteRecord | None:
        normalized = code.strip()
        if not normalized:
            return None
        normalized = normalize_source_code(normalized)
        if not updates:
            return self.repository.get_by_code(normalized)
        return self.repository.update_fields(normalized, updates)

    def create_source(
        self,
        *,
        source_code: str,
        source_name: str,
        official_url: str,
        list_url: str,
        remark: str | None,
        is_active: bool,
        schedule_enabled: bool,
        schedule_days: int,
        crawl_interval_minutes: int,
        default_max_pages: int | None,
    ) -> SourceSiteRecord:
        normalized_code = normalize_source_code(source_code.strip())
        normalized_name = source_name.strip()
        normalized_url = official_url.strip()
        normalized_list_url = list_url.strip()
        if not normalized_code:
            raise ValueError("source_code is required")
        if not normalized_name:
            raise ValueError("source_name is required")
        if not normalized_url:
            raise ValueError("official_url is required")
        if not normalized_list_url:
            raise ValueError("list_url is required")

        return self.repository.create_source(
            code=normalized_code,
            name=normalized_name,
            base_url=normalized_url,
            official_url=normalized_url,
            list_url=normalized_list_url,
            description=(remark.strip() if remark else None) or None,
            is_active=is_active,
            schedule_enabled=schedule_enabled,
            schedule_days=schedule_days,
            crawl_interval_minutes=crawl_interval_minutes,
            default_max_pages=default_max_pages,
        )
