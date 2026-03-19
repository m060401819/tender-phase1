class BaseWriter:
    """Placeholder writer for DB persistence.

    Intended for deduplication and version tracking integration.
    """

    def write(self, item: dict) -> None:
        _ = item
