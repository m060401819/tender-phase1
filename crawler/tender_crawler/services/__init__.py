"""Reusable crawler services."""

from tender_crawler.services.attachment_archive import (
    AttachmentArchiveResult,
    BaseAttachmentArchiver,
    LocalAttachmentArchiver,
    NoopAttachmentArchiver,
)
from tender_crawler.services.deduplication import (
    DeduplicationService,
    NoticeIdentity,
)

__all__ = [
    "AttachmentArchiveResult",
    "BaseAttachmentArchiver",
    "LocalAttachmentArchiver",
    "NoopAttachmentArchiver",
    "DeduplicationService",
    "NoticeIdentity",
]
