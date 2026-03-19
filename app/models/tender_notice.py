from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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


class TenderNotice(TimestampMixin, Base):
    """Canonical structured tender notice entity."""

    __tablename__ = "tender_notice"
    __table_args__ = (
        UniqueConstraint("source_site_id", "external_id", name="uq_tender_notice_source_external_id"),
        UniqueConstraint("source_site_id", "dedup_hash", name="uq_tender_notice_source_dedup_hash"),
        CheckConstraint(
            "notice_type IN ('announcement', 'change', 'result')",
            name="ck_tender_notice_type",
        ),
        Index("ix_tender_notice_source_published", "source_site_id", "published_at"),
        Index("ix_tender_notice_type", "notice_type"),
        Index("ix_tender_notice_deadline", "deadline_at"),
        Index("ix_tender_notice_region", "region"),
        Index("ix_tender_notice_issuer", "issuer"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_site_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_site.id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

    dedup_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    notice_type: Mapped[str] = mapped_column(String(32), nullable=False)

    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    budget_currency: Mapped[str] = mapped_column(String(16), nullable=False, default="CNY", server_default="CNY")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("notice_version.id", ondelete="SET NULL"),
        nullable=True,
    )

    source_site: Mapped["SourceSite"] = relationship(back_populates="tender_notices")
    versions: Mapped[list["NoticeVersion"]] = relationship(
        back_populates="notice",
        foreign_keys="NoticeVersion.notice_id",
        cascade="all, delete-orphan",
        order_by="NoticeVersion.version_no",
    )
    current_version: Mapped["NoticeVersion | None"] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )
    attachments: Mapped[list["TenderAttachment"]] = relationship(back_populates="notice")
