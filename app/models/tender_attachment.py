from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.notice_version import NoticeVersion
    from app.models.raw_document import RawDocument
    from app.models.source_site import SourceSite
    from app.models.tender_notice import TenderNotice


class TenderAttachment(TimestampMixin, Base):
    """Attachment metadata linked to notices and versions."""

    __tablename__ = "tender_attachment"
    __table_args__ = (
        UniqueConstraint("source_site_id", "url_hash", name="uq_tender_attachment_source_url_hash"),
        CheckConstraint(
            "attachment_type IN ('notice_file', 'bid_file', 'other')",
            name="ck_tender_attachment_type",
        ),
        Index("ix_tender_attachment_notice", "notice_id"),
        Index("ix_tender_attachment_notice_version", "notice_version_id"),
        Index("ix_tender_attachment_file_hash", "file_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_site_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_site.id", ondelete="RESTRICT"),
        nullable=False,
    )
    notice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tender_notice.id", ondelete="CASCADE"),
        nullable=False,
    )
    notice_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("notice_version.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_document_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_document.id", ondelete="SET NULL"),
        nullable=True,
    )

    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    attachment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="notice_file", server_default="notice_file")
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    source_site: Mapped[SourceSite] = relationship(back_populates="tender_attachments")
    notice: Mapped[TenderNotice] = relationship(back_populates="attachments")
    notice_version: Mapped[NoticeVersion | None] = relationship(back_populates="attachments")
    raw_document: Mapped[RawDocument | None] = relationship(back_populates="attachments")
