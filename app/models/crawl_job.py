from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class CrawlJob(TimestampMixin, Base):
    """Crawl execution record per source site."""

    __tablename__ = "crawl_job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'partial')",
            name="ck_crawl_job_status",
        ),
        CheckConstraint(
            "job_type IN ('scheduled', 'manual', 'backfill')",
            name="ck_crawl_job_type",
        ),
        Index("ix_crawl_job_source_started_at", "source_site_id", "started_at"),
        Index("ix_crawl_job_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_site_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_site.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled", server_default="scheduled")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    documents_saved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notices_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deduplicated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_site: Mapped["SourceSite"] = relationship(back_populates="crawl_jobs")
    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="crawl_job")
    crawl_errors: Mapped[list["CrawlError"]] = relationship(back_populates="crawl_job")
