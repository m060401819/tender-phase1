from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.crawl_error import CrawlError
    from app.models.crawl_job import CrawlJob
    from app.models.raw_document import RawDocument
    from app.models.tender_attachment import TenderAttachment
    from app.models.tender_notice import TenderNotice


class SourceSite(TimestampMixin, Base):
    """Tender source registry for multi-source crawling."""

    __tablename__ = "source_site"
    __table_args__ = (UniqueConstraint("code", name="uq_source_site_code"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    official_url: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    list_url: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    supports_js_render: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    crawl_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    default_max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_scheduled_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_scheduled_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_schedule_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    crawl_jobs: Mapped[list[CrawlJob]] = relationship(back_populates="source_site")
    raw_documents: Mapped[list[RawDocument]] = relationship(back_populates="source_site")
    tender_notices: Mapped[list[TenderNotice]] = relationship(back_populates="source_site")
    tender_attachments: Mapped[list[TenderAttachment]] = relationship(back_populates="source_site")
    crawl_errors: Mapped[list[CrawlError]] = relationship(back_populates="source_site")
