from collections import defaultdict
from lab5_crawler.common import StatsSpider
from lab5_crawler.items import QuoteItem


class QuotesSpider(StatsSpider):
    name = "quotes"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/"]

    def parse(self, response, page_number=1):
        self.record_response(response, "list")
        authors = self.state.setdefault("authors", {})
        pending = self.state.setdefault("pending", {})
        requested = self.state.setdefault("requested", [])
        groups = defaultdict(list)
        for card in response.css(".quote"):
            href = card.css("span a[href*='/author/']::attr(href)").get()
            if not href:
                self.crawler.stats.inc_value("source/missing_link")
                continue
            groups[response.urljoin(href)].append({
                "quote": card.css(".text::text").get(), "author": card.css(".author::text").get(),
                "tags": card.css(".tags .tag::text").getall(),
                "list_url": response.url, "list_page": page_number})
        for author_url, contexts in groups.items():
            if author_url in authors:
                self.crawler.stats.inc_value("source/author_reused", len(contexts))
                for context in contexts:
                    yield QuoteItem(kind="quote", **context, **authors[author_url])
            elif author_url in requested:
                pending.setdefault(author_url, []).extend(contexts)
            else:
                requested.append(author_url)
                yield response.follow(author_url, callback=self.parse_item, errback=self.errback,
                    cb_kwargs={"contexts": contexts, "author_url": author_url}, priority=1)
        next_page = response.css("li.next a::attr(href)").get()
        if next_page and page_number < self.max_pages:
            yield response.follow(next_page, callback=self.parse, errback=self.errback,
                                  cb_kwargs={"page_number": page_number + 1}, priority=-1)

    def parse_item(self, response, contexts, author_url):
        self.record_response(response, "detail")
        details = {"born_date": response.css(".author-born-date::text").get(),
                   "born_location": response.css(".author-born-location::text").get(),
                   "biography": " ".join(response.css(".author-description::text").getall()) or None,
                   "source_url": response.url}
        self.state["authors"][author_url] = details
        contexts += self.state["pending"].pop(author_url, [])
        for context in contexts:
            yield QuoteItem(kind="quote", **context, **details)
