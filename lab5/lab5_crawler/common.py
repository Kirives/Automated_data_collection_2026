import json
import re
from datetime import datetime, timezone
from pathlib import Path
import scrapy


class StatsSpider(scrapy.Spider):
    def __init__(self, run_id=None, max_pages=15, **kwargs):
        super().__init__(**kwargs)
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + self.name
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.run_id):
            raise ValueError("Некорректный run_id")
        self.max_pages = int(max_pages)
        self.state = {}
        self.parsed_urls = []

    async def start(self):
        for url in self.start_urls:
            # При возобновлении стартовая страница тоже проходит dupefilter.
            yield scrapy.Request(url, callback=self.parse, errback=self.errback, dont_filter=False)

    def record_response(self, response, level):
        self.crawler.stats.inc_value("source/" + level + "_pages")
        self.crawler.stats.inc_value("traffic/body_bytes", len(response.body))
        self.parsed_urls.append(response.url)

    def errback(self, failure):
        self.crawler.stats.inc_value("network/errbacks")
        self.logger.error("Ошибка %s: %s", failure.request.url, failure.getErrorMessage())

    def closed(self, reason):
        stats = dict(self.crawler.stats.get_stats())
        finished = datetime.now(timezone.utc)
        stats.update(run_id=self.run_id, spider=self.name, finish_reason=reason,
                     finish_time=finished, parsed_urls=self.parsed_urls,
                     max_list_pages=self.max_pages,
                     database_path=self.settings.get("DATABASE_PATH"))
        if isinstance(stats.get("start_time"), datetime):
            stats["elapsed_time_seconds"] = (finished - stats["start_time"]).total_seconds()
        directory = Path(self.settings.get("STATS_DIR", "data"))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"stats_{self.run_id}.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
