from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from tender_crawler.utils import sha256_text


@dataclass(slots=True)
class AttachmentArchiveResult:
    storage_uri: str | None = None
    file_hash: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None


class BaseAttachmentArchiver:
    """Archive attachment file payloads and return normalized metadata."""

    def archive(self, item: dict[str, Any]) -> AttachmentArchiveResult:
        raise NotImplementedError


class NoopAttachmentArchiver(BaseAttachmentArchiver):
    """No-op archiver to keep default crawler behavior unchanged."""

    def archive(self, item: dict[str, Any]) -> AttachmentArchiveResult:
        return AttachmentArchiveResult(
            storage_uri=_as_str(item.get("storage_uri")),
            file_hash=_as_str(item.get("file_hash")),
            mime_type=_as_str(item.get("mime_type")),
            file_size_bytes=_as_int(item.get("file_size_bytes")),
        )


class LocalAttachmentArchiver(BaseAttachmentArchiver):
    """Download attachment files and archive to local filesystem."""

    _ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

    def __init__(self, *, base_dir: str = "data/attachments", timeout_seconds: float = 20.0) -> None:
        self.base_dir = Path(base_dir)
        self.timeout_seconds = timeout_seconds

    def archive(self, item: dict[str, Any]) -> AttachmentArchiveResult:
        file_url = _as_str(item.get("file_url"))
        if not file_url:
            return AttachmentArchiveResult(
                storage_uri=_as_str(item.get("storage_uri")),
                file_hash=_as_str(item.get("file_hash")),
                mime_type=_as_str(item.get("mime_type")),
                file_size_bytes=_as_int(item.get("file_size_bytes")),
            )

        parsed_url = urlparse(file_url)
        if parsed_url.scheme.lower() not in self._ALLOWED_URL_SCHEMES:
            raise ValueError(f"unsupported attachment url scheme: {parsed_url.scheme or '(empty)'}")

        request = Request(file_url, headers={"User-Agent": "tender-phase1-crawler/1.0"})
        # Bandit B310 reviewed: attachment downloads are restricted to http/https.
        with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310
            payload = response.read()
            mime_type = response.headers.get_content_type() if response.headers else None

        url_hash = _as_str(item.get("url_hash")) or sha256_text(file_url)
        ext = self._choose_extension(item=item, mime_type=mime_type, url=file_url)

        source_code = _as_str(item.get("source_code")) or "unknown_source"
        sub_dir = self.base_dir / source_code / url_hash[:2]
        sub_dir.mkdir(parents=True, exist_ok=True)
        output_path = sub_dir / f"{url_hash}{ext}"
        output_path.write_bytes(payload)

        return AttachmentArchiveResult(
            storage_uri=str(output_path),
            file_hash=hashlib.sha256(payload).hexdigest(),
            mime_type=mime_type or _as_str(item.get("mime_type")),
            file_size_bytes=len(payload),
        )

    def _choose_extension(self, *, item: dict[str, Any], mime_type: str | None, url: str) -> str:
        explicit_ext = _as_str(item.get("file_ext"))
        if explicit_ext:
            return f".{explicit_ext.lstrip('.')}"

        file_name = _as_str(item.get("file_name"))
        if file_name and "." in file_name:
            suffix = Path(file_name).suffix
            if suffix:
                return suffix

        parsed = urlparse(url)
        url_suffix = Path(parsed.path).suffix
        if url_suffix:
            return url_suffix

        if mime_type:
            guessed = mimetypes.guess_extension(mime_type)
            if guessed:
                return guessed

        return ".bin"


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
