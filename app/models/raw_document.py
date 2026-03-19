from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class RawDocument(TimestampMixin, Base):
    """Archived raw document metadata separated from structured notice data."""

    __tablename__ = "raw_document"
    __table_args__ = (
        UniqueConstraint("source_site_id", "url_hash", name="uq_raw_document_source_url_hash"),
        CheckConstraint(
            "document_type IN ('html', 'pdf', 'json', 'other')",
            name="ck_raw_document_type",
        ),
        Index("ix_raw_document_url_hash", "url_hash"),
        Index("ix_raw_document_content_hash", "content_hash"),
        Index("ix_raw_document_crawl_job", "crawl_job_id"),
        Index("ix_raw_document_fetched_at", "fetched_at"),
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

    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    document_type: Mapped[str] = mapped_column(String(16), nullable=False, default="html", server_default="html")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    charset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_duplicate_url: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_duplicate_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    extra_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    source_site: Mapped["SourceSite"] = relationship(back_populates="raw_documents")
    crawl_job: Mapped["CrawlJob | None"] = relationship(back_populates="raw_documents")
    notice_versions: Mapped[list["NoticeVersion"]] = relationship(back_populates="raw_document")
    attachments: Mapped[list["TenderAttachment"]] = relationship(back_populates="raw_document")
    crawl_errors: Mapped[list["CrawlError"]] = relationship(back_populates="raw_document")
