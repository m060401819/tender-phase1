from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class SourceSite(TimestampMixin, Base):
    """Tender source registry for multi-source crawling."""

    __tablename__ = "source_site"
    __table_args__ = (UniqueConstraint("code", name="uq_source_site_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    supports_js_render: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    crawl_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    default_max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    crawl_jobs: Mapped[list["CrawlJob"]] = relationship(back_populates="source_site")
    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="source_site")
    tender_notices: Mapped[list["TenderNotice"]] = relationship(back_populates="source_site")
    tender_attachments: Mapped[list["TenderAttachment"]] = relationship(back_populates="source_site")
    crawl_errors: Mapped[list["CrawlError"]] = relationship(back_populates="source_site")
