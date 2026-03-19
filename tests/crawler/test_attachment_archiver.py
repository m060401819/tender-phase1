from __future__ import annotations

from pathlib import Path

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
    result = archiver.archive(
        {
            "source_code": "example_source",
            "file_url": source_file.as_uri(),
            "file_name": "source.pdf",
            "url_hash": "abc123",
            "file_ext": "pdf",
        }
    )

    assert result.storage_uri is not None
    archived = Path(result.storage_uri)
    assert archived.exists()
    assert archived.read_bytes() == b"pdf-binary-content"
    assert result.file_hash is not None
    assert result.file_size_bytes == len(b"pdf-binary-content")
