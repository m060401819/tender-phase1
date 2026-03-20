from __future__ import annotations

from app.repositories import StatsOverviewRecord, StatsRepository


class StatsService:
    """Service layer for system overview statistics."""

    def __init__(self, repository: StatsRepository) -> None:
        self.repository = repository

    def get_overview(self) -> StatsOverviewRecord:
        return self.repository.get_overview()
