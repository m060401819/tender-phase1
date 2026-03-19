from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class RawArchivePipeline:
    """Archive raw HTML and metadata to local filesystem.

    Phase-1 placeholder implementation to enforce raw-page retention.
    """

    def __init__(self, base_dir: str = "data/raw") -> None:
        self.base_path = Path(base_dir)

    @classmethod
    def from_crawler(cls, crawler):  # type: ignore[no-untyped-def]
        base_dir = crawler.settings.get("RAW_ARCHIVE_DIR", "data/raw")
        return cls(base_dir=base_dir)

    def process_item(self, item: dict, spider):  # type: ignore[no-untyped-def]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        source = item.get("source", spider.name)
        source_dir = self.base_path / source
        source_dir.mkdir(parents=True, exist_ok=True)

        html_file = source_dir / f"{timestamp}.html"
        meta_file = source_dir / f"{timestamp}.json"

        html_file.write_text(item.get("raw_html", ""), encoding="utf-8")
        metadata = {
            "source": source,
            "url": item.get("url", ""),
            "fetched_at": item.get("fetched_at", timestamp),
            "archive_html": str(html_file),
        }
        meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return item
