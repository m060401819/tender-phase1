BOT_NAME = "tender_crawler"

SPIDER_MODULES = ["tender_crawler.spiders"]
NEWSPIDER_MODULE = "tender_crawler.spiders"

ROBOTSTXT_OBEY = False

# Keep crawl, parse and write separated by module responsibilities.
ITEM_PIPELINES = {
    "tender_crawler.pipelines.RawArchivePipeline": 300,
}

RAW_ARCHIVE_DIR = "data/raw"
