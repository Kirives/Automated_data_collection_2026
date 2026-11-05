BOT_NAME = "lab5_crawler"
SPIDER_MODULES = ["lab5_crawler.spiders"]
NEWSPIDER_MODULE = "lab5_crawler.spiders"
# Учебные сайты; ограничения robots.txt учитываются автоматически.
USER_AGENT = "UniversityLab5/1.0 (educational crawl on toscrape.com)"
ROBOTSTXT_OBEY = True
# Максимум два одновременных запроса к одному домену.
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 0.5
RANDOMIZE_DOWNLOAD_DELAY = True
# При медленных ответах задержка увеличивается автоматически.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
DOWNLOAD_TIMEOUT = 25
RETRY_TIMES = 2
RETRY_HTTP_CODES = [408, 429, 500, 502, 503, 504, 522, 524]
# Глубина включает последовательные переходы пагинации.
DEPTH_LIMIT = 60
# Ограничители от случайного бесконечного обхода.
CLOSESPIDER_ITEMCOUNT = 350
CLOSESPIDER_PAGECOUNT = 500
CLOSESPIDER_TIMEOUT = 900
CLOSESPIDER_ERRORCOUNT = 10
# Для основного сбора кэш выключен; включаем только в отдельном опыте.
HTTPCACHE_ENABLED = False
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_EXPIRATION_SECS = 86400
HTTPCACHE_IGNORE_HTTP_CODES = [429, 500, 502, 503, 504]
HTTPCACHE_POLICY = "scrapy.extensions.httpcache.DummyPolicy"
ITEM_PIPELINES = {
    "lab5_crawler.pipelines.ValidatePipeline": 100,
    "lab5_crawler.pipelines.CleanPipeline": 200,
    "lab5_crawler.pipelines.DeduplicatePipeline": 300,
    "lab5_crawler.pipelines.DatabasePipeline": 400,
}
DATABASE_PATH = "data/crawl.db"
DATABASE_BATCH_SIZE = 25
STATS_DIR = "data"
LOG_LEVEL = "INFO"
LOGSTATS_INTERVAL = 30
FEED_EXPORT_ENCODING = "utf-8"
# Несжатые тела ответов позволяют сравнить трафик с n8n.
DEFAULT_REQUEST_HEADERS = {"Accept": "text/html", "Accept-Language": "en", "Accept-Encoding": "identity"}
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
SCHEDULER_DEBUG = True
