from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from tender_crawler.services import LocalAttachmentArchiver, NoopAttachmentArchiver


def test_noop_attachment_archiver_returns_existing_fields() -> None:
    archiver = NoopAttachmentArchiver()
    result = archiver.archive(
        {
            "storage_uri": "data/attachments/a.pdf",
            "file_hash": "h1",
            "mime_type": "application/pdf",
            "file_size_bytes": 12,
        }
    )

    assert result.storage_uri == "data/attachments/a.pdf"
    assert result.file_hash == "h1"
    assert result.mime_type == "application/pdf"
    assert result.file_size_bytes == 12


def test_local_attachment_archiver_downloads_and_archives_file(tmp_path: Path) -> None:
    source_file = tmp_path / "source.pdf"
    source_file.write_bytes(b"pdf-binary-content")

    archiver = LocalAttachmentArchiver(base_dir=str(tmp_path / "archive"), timeout_seconds=5)

    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = archiver.archive(
            {
                "source_code": "example_source",
                "file_url": f"http://127.0.0.1:{server.server_port}/source.pdf",
                "file_name": "source.pdf",
                "url_hash": "abc123",
                "file_ext": "pdf",
            }
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.storage_uri is not None
    archived = Path(result.storage_uri)
    assert archived.exists()
    assert archived.read_bytes() == b"pdf-binary-content"
    assert result.file_hash is not None
    assert result.file_size_bytes == len(b"pdf-binary-content")


def test_local_attachment_archiver_rejects_non_http_scheme(tmp_path: Path) -> None:
    source_file = tmp_path / "source.pdf"
    source_file.write_bytes(b"pdf-binary-content")
    archiver = LocalAttachmentArchiver(base_dir=str(tmp_path / "archive"), timeout_seconds=5)

    with pytest.raises(ValueError, match="unsupported attachment url scheme"):
        archiver.archive(
            {
                "source_code": "example_source",
                "file_url": source_file.as_uri(),
                "file_name": "source.pdf",
                "url_hash": "abc123",
                "file_ext": "pdf",
            }
        )
