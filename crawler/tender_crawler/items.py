from dataclasses import dataclass


@dataclass
class RawTenderItem:
    source: str
    url: str
    fetched_at: str
    raw_html: str
