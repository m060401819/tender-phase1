from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BaseWriter:
    """Base writer lifecycle hooks."""

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None


class BaseRawDocumentWriter(BaseWriter):
    def write_raw_document(self, item: dict[str, Any]) -> None:
        raise NotImplementedError


class BaseNoticeWriter(BaseWriter):
    def write_notice(self, item: dict[str, Any]) -> None:
        raise NotImplementedError

    def write_notice_version(self, item: dict[str, Any]) -> None:
        raise NotImplementedError

    def write_attachment(self, item: dict[str, Any]) -> None:
        raise NotImplementedError


class BaseErrorWriter(BaseWriter):
    def write_error(self, item: dict[str, Any]) -> None:
        raise NotImplementedError


class NoopRawDocumentWriter(BaseRawDocumentWriter):
    """No-op raw writer reserved for future DB integration."""

    def write_raw_document(self, item: dict[str, Any]) -> None:
        _ = item


class NoopNoticeWriter(BaseNoticeWriter):
    """No-op structured writer reserved for future DB integration."""

    def write_notice(self, item: dict[str, Any]) -> None:
        _ = item

    def write_notice_version(self, item: dict[str, Any]) -> None:
        _ = item

    def write_attachment(self, item: dict[str, Any]) -> None:
        _ = item


class NoopErrorWriter(BaseErrorWriter):
    """No-op error writer reserved for future DB integration."""

    def write_error(self, item: dict[str, Any]) -> None:
        _ = item


@dataclass(slots=True)
class WriterBundle:
    """Group writers to keep pipeline orchestration simple."""

    raw_document_writer: BaseRawDocumentWriter
    notice_writer: BaseNoticeWriter
    error_writer: BaseErrorWriter

    def open(self) -> None:
        self.raw_document_writer.open()
        self.notice_writer.open()
        self.error_writer.open()

    def close(self) -> None:
        self.raw_document_writer.close()
        self.notice_writer.close()
        self.error_writer.close()
