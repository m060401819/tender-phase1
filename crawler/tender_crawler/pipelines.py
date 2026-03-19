from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from itemadapter import ItemAdapter

from tender_crawler.items import (
    ITEM_TYPE_CRAWL_ERROR,
    ITEM_TYPE_NOTICE_VERSION,
    ITEM_TYPE_RAW_DOCUMENT,
    ITEM_TYPE_TENDER_ATTACHMENT,
    ITEM_TYPE_TENDER_NOTICE,
    get_item_type,
)
from tender_crawler.services import (
    BaseAttachmentArchiver,
    LocalAttachmentArchiver,
    NoopAttachmentArchiver,
)
from tender_crawler.utils import sha256_text, utcnow_iso
from tender_crawler.writers.factory import build_writer_bundle


class BasePipeline:
    """Base pipeline class for future extension."""

    def open_spider(self, spider):  # type: ignore[no-untyped-def]
        return None

    def close_spider(self, spider):  # type: ignore[no-untyped-def]
        return None

    def process_item(self, item: object, spider):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class RawArchivePipeline(BasePipeline):
    """Archive raw HTML and metadata before writing to storage/DB."""

    def __init__(self, base_dir: str = "data/raw") -> None:
        self.base_path = Path(base_dir)

    @classmethod
    def from_crawler(cls, crawler):  # type: ignore[no-untyped-def]
        base_dir = crawler.settings.get("RAW_ARCHIVE_DIR", "data/raw")
        return cls(base_dir=base_dir)

    def process_item(self, item: object, spider):  # type: ignore[no-untyped-def]
        if get_item_type(item) != ITEM_TYPE_RAW_DOCUMENT:
            return item

        adapter = ItemAdapter(item)
        source = str(adapter.get("source_code") or spider.name)
        url = str(adapter.get("url") or "")
        timestamp = utcnow_iso().replace(":", "-")

        source_dir = self.base_path / source
        source_dir.mkdir(parents=True, exist_ok=True)

        url_suffix = sha256_text(url)[:12]
        html_file = source_dir / f"{timestamp}_{url_suffix}.html"
        meta_file = source_dir / f"{timestamp}_{url_suffix}.json"

        raw_body = str(adapter.get("raw_body") or "")
        html_file.write_text(raw_body, encoding="utf-8")

        existing_meta = dict(adapter.get("extra_meta") or {})
        existing_meta.update(
            {
                "archive_html": str(html_file),
                "archive_meta": str(meta_file),
                "archived_at": utcnow_iso(),
            }
        )
        adapter["extra_meta"] = existing_meta

        if not adapter.get("storage_uri"):
            adapter["storage_uri"] = str(html_file)
        if not adapter.get("content_length"):
            adapter["content_length"] = len(raw_body.encode("utf-8"))

        metadata = {
            "item_type": adapter.get("item_type"),
            "source_code": source,
            "url": url,
            "fetched_at": adapter.get("fetched_at"),
            "storage_uri": adapter.get("storage_uri"),
            "content_hash": adapter.get("content_hash"),
            "url_hash": adapter.get("url_hash"),
            "extra_meta": existing_meta,
        }
        meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return item


class AttachmentArchivePipeline(BasePipeline):
    """Optional attachment downloader/archive stage before writer dispatch."""

    def __init__(self, archiver: BaseAttachmentArchiver) -> None:
        self.archiver = archiver

    @classmethod
    def from_crawler(cls, crawler):  # type: ignore[no-untyped-def]
        backend = str(crawler.settings.get("ATTACHMENT_ARCHIVER_BACKEND", "noop")).lower()
        archive_dir = str(crawler.settings.get("ATTACHMENT_ARCHIVE_DIR", "data/attachments"))
        timeout_seconds = float(crawler.settings.get("ATTACHMENT_ARCHIVE_TIMEOUT_SECONDS", 20))

        if backend == "local":
            archiver: BaseAttachmentArchiver = LocalAttachmentArchiver(
                base_dir=archive_dir,
                timeout_seconds=timeout_seconds,
            )
        else:
            archiver = NoopAttachmentArchiver()
        return cls(archiver=archiver)

    def process_item(self, item: object, spider):  # type: ignore[no-untyped-def]
        if get_item_type(item) != ITEM_TYPE_TENDER_ATTACHMENT:
            return item

        adapter = ItemAdapter(item)
        result = self.archiver.archive(adapter.asdict())

        if result.storage_uri:
            adapter["storage_uri"] = result.storage_uri
            if not adapter.get("downloaded_at"):
                adapter["downloaded_at"] = utcnow_iso()
        if result.file_hash:
            adapter["file_hash"] = result.file_hash
        if result.mime_type and not adapter.get("mime_type"):
            adapter["mime_type"] = result.mime_type
        if result.file_size_bytes is not None and not adapter.get("file_size_bytes"):
            adapter["file_size_bytes"] = result.file_size_bytes

        return item


class WriterDispatchPipeline(BasePipeline):
    """Dispatch parsed items to writer layer (DB/file pluggable)."""

    def __init__(self, writer_bundle) -> None:
        self.writer_bundle = writer_bundle

    @classmethod
    def from_crawler(cls, crawler):  # type: ignore[no-untyped-def]
        return cls(writer_bundle=build_writer_bundle(crawler.settings))

    def open_spider(self, spider):  # type: ignore[no-untyped-def]
        self.writer_bundle.open()

    def close_spider(self, spider):  # type: ignore[no-untyped-def]
        self.writer_bundle.close()

    def process_item(self, item: object, spider):  # type: ignore[no-untyped-def]
        item_type = get_item_type(item)
        if item_type is None:
            return item

        payload: dict[str, Any] = ItemAdapter(item).asdict()

        if item_type == ITEM_TYPE_RAW_DOCUMENT:
            self.writer_bundle.raw_document_writer.write_raw_document(payload)
        elif item_type == ITEM_TYPE_TENDER_NOTICE:
            self.writer_bundle.notice_writer.write_notice(payload)
        elif item_type == ITEM_TYPE_NOTICE_VERSION:
            self.writer_bundle.notice_writer.write_notice_version(payload)
        elif item_type == ITEM_TYPE_TENDER_ATTACHMENT:
            self.writer_bundle.notice_writer.write_attachment(payload)
        elif item_type == ITEM_TYPE_CRAWL_ERROR:
            self.writer_bundle.error_writer.write_error(payload)
        else:
            spider.logger.debug("Skip unsupported item_type=%s", item_type)

        return item
