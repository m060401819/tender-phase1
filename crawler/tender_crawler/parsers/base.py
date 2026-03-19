class BaseTenderParser:
    """Placeholder parser for Phase-1 normalized fields extraction."""

    def parse(self, raw_html: str) -> dict:
        return {
            "title": "",
            "published_at": None,
            "region": "",
            "industry_tags": [],
            "raw_length": len(raw_html),
        }
