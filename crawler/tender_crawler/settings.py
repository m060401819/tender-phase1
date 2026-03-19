BOT_NAME = "tender_crawler"

SPIDER_MODULES = ["tender_crawler.spiders"]
NEWSPIDER_MODULE = "tender_crawler.spiders"

ROBOTSTXT_OBEY = False
LOG_LEVEL = "INFO"

# Keep crawl, parse and write separated by module responsibilities.
ITEM_PIPELINES = {
    "tender_crawler.pipelines.RawArchivePipeline": 100,
    "tender_crawler.pipelines.AttachmentArchivePipeline": 200,
    "tender_crawler.pipelines.WriterDispatchPipeline": 300,
}

# Raw archive location, maps to `raw_document.storage_uri` lifecycle.
RAW_ARCHIVE_DIR = "data/raw"

# Writer backend: `jsonl` for local staging, `sqlalchemy` for DB writing, `noop` for dry-run.
CRAWLER_WRITER_BACKEND = "jsonl"
CRAWLER_WRITER_OUTPUT_DIR = "data/staging"
CRAWLER_DATABASE_URL = ""

# Attachment archive backend: `noop` (default) or `local` (download and archive files).
ATTACHMENT_ARCHIVER_BACKEND = "noop"
ATTACHMENT_ARCHIVE_DIR = "data/attachments"
ATTACHMENT_ARCHIVE_TIMEOUT_SECONDS = 20

# Playwright fallback reservation (disabled by default).
PLAYWRIGHT_FALLBACK_ENABLED = False
PLAYWRIGHT_TIMEOUT_MS = 30000
