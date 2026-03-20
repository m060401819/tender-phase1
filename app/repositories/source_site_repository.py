from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceSite


@dataclass(slots=True)
class SourceSiteRecord:
    id: int
    code: str
    name: str
    base_url: str
    description: str | None
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int
    default_max_pages: int


class SourceSiteRepository:
    """SQLAlchemy repository for source_site queries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_sources(self) -> list[SourceSiteRecord]:
        rows = self.session.scalars(select(SourceSite).order_by(SourceSite.code.asc())).all()
        return [self._to_record(source) for source in rows]

    def get_by_code(self, code: str) -> SourceSiteRecord | None:
        source = self.session.scalar(select(SourceSite).where(SourceSite.code == code))
        if source is None:
            return None
        return self._to_record(source)

    def get_model_by_code(self, code: str) -> SourceSite | None:
        return self.session.scalar(select(SourceSite).where(SourceSite.code == code))

    def update_fields(self, code: str, updates: dict[str, bool | int]) -> SourceSiteRecord | None:
        source = self.get_model_by_code(code)
        if source is None:
            return None

        for key, value in updates.items():
            setattr(source, key, value)

        self.session.add(source)
        self.session.commit()
        self.session.refresh(source)
        return self._to_record(source)

    def _to_record(self, source: SourceSite) -> SourceSiteRecord:
        return SourceSiteRecord(
            id=int(source.id),
            code=source.code,
            name=source.name,
            base_url=source.base_url,
            description=source.description,
            is_active=bool(source.is_active),
            supports_js_render=bool(source.supports_js_render),
            crawl_interval_minutes=int(source.crawl_interval_minutes),
            default_max_pages=int(source.default_max_pages),
        )
