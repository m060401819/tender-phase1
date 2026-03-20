from __future__ import annotations

from app.repositories import SourceSiteRecord, SourceSiteRepository


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
        return self.repository.get_by_code(normalized)

    def update_source(self, code: str, updates: dict[str, bool | int]) -> SourceSiteRecord | None:
        normalized = code.strip()
        if not normalized:
            return None
        if not updates:
            return self.repository.get_by_code(normalized)
        return self.repository.update_fields(normalized, updates)
