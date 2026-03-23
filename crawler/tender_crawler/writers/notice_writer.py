from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from tender_crawler.writers.base import BaseNoticeWriter


class JsonlNoticeWriter(BaseNoticeWriter):
    """Write structured notice payloads to JSONL, as DB writing placeholder."""

    def __init__(self, output_dir: str = "data/staging") -> None:
        base = Path(output_dir)
        self.output_dir = base
        self.notice_path = base / "tender_notice.jsonl"
        self.version_path = base / "notice_version.jsonl"
        self.attachment_path = base / "tender_attachment.jsonl"

        self._notice_fp: TextIO | None = None
        self._version_fp: TextIO | None = None
        self._attachment_fp: TextIO | None = None

    def open(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._notice_fp = self.notice_path.open("a", encoding="utf-8")
        self._version_fp = self.version_path.open("a", encoding="utf-8")
        self._attachment_fp = self.attachment_path.open("a", encoding="utf-8")

    def close(self) -> None:
        for fp_name in ("_notice_fp", "_version_fp", "_attachment_fp"):
            fp = getattr(self, fp_name)
            if fp is not None:
                fp.close()
                setattr(self, fp_name, None)

    def write_notice(self, item: dict) -> None:
        if self._notice_fp is None:
            self.open()
        if self._notice_fp is None:
            raise RuntimeError("notice writer file handle is not available")
        self._notice_fp.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._notice_fp.flush()

    def write_notice_version(self, item: dict) -> None:
        if self._version_fp is None:
            self.open()
        if self._version_fp is None:
            raise RuntimeError("notice version writer file handle is not available")
        self._version_fp.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._version_fp.flush()

    def write_attachment(self, item: dict) -> None:
        if self._attachment_fp is None:
            self.open()
        if self._attachment_fp is None:
            raise RuntimeError("attachment writer file handle is not available")
        self._attachment_fp.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._attachment_fp.flush()
