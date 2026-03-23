from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class CrawlJob(TimestampMixin, Base):
    """Single-owner crawl execution record per source site."""

    __tablename__ = "crawl_job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'partial')",
            name="ck_crawl_job_status",
        ),
        CheckConstraint(
            "job_type IN ('scheduled', 'manual', 'backfill', 'manual_retry')",
            name="ck_crawl_job_type",
        ),
        UniqueConstraint("retry_of_job_id", name="uq_crawl_job_retry_of_job_id"),
        Index("ix_crawl_job_source_started_at", "source_site_id", "started_at"),
        Index("ix_crawl_job_status", "status"),
        Index("ix_crawl_job_retry_of_job_id", "retry_of_job_id"),
        Index("ix_crawl_job_timeout_at", "timeout_at"),
        Index(
            "uq_crawl_job_source_active",
            "source_site_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
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
    retry_of_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("crawl_job.id", ondelete="SET NULL"),
        nullable=True,
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    documents_saved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notices_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deduplicated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    list_items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    list_items_unique: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    list_items_source_duplicates_skipped: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    detail_pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_duplicates_suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    job_params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    runtime_stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_site: Mapped["SourceSite"] = relationship(back_populates="crawl_jobs")
    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="crawl_job")
    crawl_errors: Mapped[list["CrawlError"]] = relationship(back_populates="crawl_job")
