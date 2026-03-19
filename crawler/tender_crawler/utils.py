from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def sha256_text(value: str) -> str:
    """Return SHA-256 hash for text values."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    """Normalize URL by lowercasing host, removing fragment and sorting query string."""
    split = urlsplit(url.strip())
    netloc = split.netloc.lower()
    query = urlencode(sorted(parse_qsl(split.query, keep_blank_values=True)))
    return urlunsplit((split.scheme.lower(), netloc, split.path or "/", query, ""))


def utcnow_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()
