from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import SourceSite


@dataclass(slots=True)
class SourceSiteRecord:
    id: int
    code: str
    name: str
    base_url: str
    official_url: str
    list_url: str
    description: str | None
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int
    default_max_pages: int
    schedule_enabled: bool
    schedule_days: int
    last_scheduled_run_at: datetime | None
    next_scheduled_run_at: datetime | None
    last_schedule_status: str | None


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

    def update_fields(self, code: str, updates: dict[str, object]) -> SourceSiteRecord | None:
        source = self.get_model_by_code(code)
        if source is None:
            return None

        for key, value in updates.items():
            setattr(source, key, value)

        self.session.add(source)
        self.session.commit()
        self.session.refresh(source)
        return self._to_record(source)

    def create_source(
        self,
        *,
        code: str,
        name: str,
        base_url: str,
        official_url: str,
        list_url: str,
        description: str | None,
        is_active: bool,
        schedule_enabled: bool,
        schedule_days: int,
        crawl_interval_minutes: int,
        default_max_pages: int | None,
    ) -> SourceSiteRecord:
        source = SourceSite(
            code=code,
            name=name,
            base_url=base_url,
            official_url=official_url,
            list_url=list_url,
            description=description,
            is_active=is_active,
            supports_js_render=False,
            crawl_interval_minutes=crawl_interval_minutes,
            default_max_pages=default_max_pages or 50,
            schedule_enabled=schedule_enabled,
            schedule_days=schedule_days,
        )
        self.session.add(source)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if _is_source_code_conflict(exc):
                raise ValueError("source_code already exists") from exc
            raise
        self.session.refresh(source)
        return self._to_record(source)

    def _to_record(self, source: SourceSite) -> SourceSiteRecord:
        return SourceSiteRecord(
            id=int(source.id),
            code=source.code,
            name=source.name,
            base_url=source.base_url,
            official_url=source.official_url or source.base_url,
            list_url=source.list_url or source.base_url,
            description=source.description,
            is_active=bool(source.is_active),
            supports_js_render=bool(source.supports_js_render),
            crawl_interval_minutes=int(source.crawl_interval_minutes),
            default_max_pages=int(source.default_max_pages),
            schedule_enabled=bool(source.schedule_enabled),
            schedule_days=int(source.schedule_days),
            last_scheduled_run_at=source.last_scheduled_run_at,
            next_scheduled_run_at=source.next_scheduled_run_at,
            last_schedule_status=source.last_schedule_status,
        )


def _is_source_code_conflict(error: IntegrityError) -> bool:
    raw_message = str(error.orig).lower()
    return (
        "uq_source_site_code" in raw_message
        or "source_site.code" in raw_message
        or "unique constraint failed: source_site.code" in raw_message
    )
