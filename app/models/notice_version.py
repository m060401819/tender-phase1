from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class NoticeVersion(TimestampMixin, Base):
    """Historical versions of the same tender notice."""

    __tablename__ = "notice_version"
    __table_args__ = (
        UniqueConstraint("notice_id", "version_no", name="uq_notice_version_notice_version_no"),
        UniqueConstraint("notice_id", "content_hash", name="uq_notice_version_notice_content_hash"),
        CheckConstraint(
            "notice_type IN ('announcement', 'change', 'result')",
            name="ck_notice_version_type",
        ),
        Index("ix_notice_version_content_hash", "content_hash"),
        Index("ix_notice_version_notice_current", "notice_id", "is_current"),
        Index("ix_notice_version_raw_document", "raw_document_id"),
        Index("ix_notice_version_dedup_key", "dedup_key"),
        Index("ix_notice_version_source_duplicate_key", "source_duplicate_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    notice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tender_notice.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_document_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("raw_document.id", ondelete="SET NULL"),
        nullable=True,
    )

    version_no: Mapped[int] = mapped_column(nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_duplicate_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    notice_type: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    budget_currency: Mapped[str] = mapped_column(String(16), nullable=False, default="CNY", server_default="CNY")

    structured_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    notice: Mapped["TenderNotice"] = relationship(
        back_populates="versions",
        foreign_keys=[notice_id],
    )
    raw_document: Mapped["RawDocument | None"] = relationship(back_populates="notice_versions")
    attachments: Mapped[list["TenderAttachment"]] = relationship(back_populates="notice_version")
