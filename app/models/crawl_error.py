from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class CrawlError(TimestampMixin, Base):
    """Error events happened during crawl / parse / persistence phases."""

    __tablename__ = "crawl_error"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('fetch', 'parse', 'persist')",
            name="ck_crawl_error_stage",
        ),
        Index("ix_crawl_error_source_occurred", "source_site_id", "occurred_at"),
        Index("ix_crawl_error_job", "crawl_job_id"),
        Index("ix_crawl_error_raw_document", "raw_document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_site_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_site.id", ondelete="RESTRICT"),
        nullable=False,
    )
    crawl_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("crawl_job.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_document_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_document.id", ondelete="SET NULL"),
        nullable=True,
    )

    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="fetch", server_default="fetch")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str] = mapped_column(String(255), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    source_site: Mapped["SourceSite"] = relationship(back_populates="crawl_errors")
    crawl_job: Mapped["CrawlJob | None"] = relationship(back_populates="crawl_errors")
    raw_document: Mapped["RawDocument | None"] = relationship(back_populates="crawl_errors")
