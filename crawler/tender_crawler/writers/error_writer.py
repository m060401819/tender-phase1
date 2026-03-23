from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from tender_crawler.writers.base import BaseErrorWriter


class JsonlErrorWriter(BaseErrorWriter):
    """Write crawl errors to JSONL, as DB writing placeholder."""

    def __init__(self, output_dir: str = "data/staging") -> None:
        self.output_dir = Path(output_dir)
        self.file_path = self.output_dir / "crawl_error.jsonl"
        self._fp: TextIO | None = None

    def open(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._fp = self.file_path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def write_error(self, item: dict) -> None:
        if self._fp is None:
            self.open()
        if self._fp is None:
            raise RuntimeError("crawl error writer file handle is not available")
        self._fp.write(json.dumps(item, ensure_ascii=False) + "\n")
        self._fp.flush()
