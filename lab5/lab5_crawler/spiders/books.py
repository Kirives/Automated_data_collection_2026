from lab5_crawler.common import StatsSpider
from lab5_crawler.items import BookItem


class BooksSpider(StatsSpider):
    name = "books"
    allowed_domains = ["books.toscrape.com"]
    start_urls = ["https://books.toscrape.com/catalogue/page-1.html"]

    def parse(self, response, page_number=1):
        self.record_response(response, "list")
        for card in response.css("article.product_pod"):
            href = card.css("h3 a::attr(href)").get()
            if href:
                yield response.follow(href, callback=self.parse_item, errback=self.errback,
                    cb_kwargs={"list_url": response.url, "list_page": page_number,
                               "listed_title": card.css("h3 a::attr(title)").get()})
            else:
                self.crawler.stats.inc_value("source/missing_link")
        next_page = response.css("li.next a::attr(href)").get()
        if next_page and page_number < self.max_pages:
            yield response.follow(next_page, callback=self.parse, errback=self.errback,
                                  cb_kwargs={"page_number": page_number + 1}, priority=-1)

    def parse_item(self, response, list_url, list_page, listed_title):
        self.record_response(response, "detail")
        table = {row.css("th::text").get(): row.css("td::text").get()
                 for row in response.css("table.table tr")}
        yield BookItem(kind="book", upc=table.get("UPC"),
            title=response.css(".product_main h1::text").get() or listed_title,
            price_excl_tax=table.get("Price (excl. tax)"), stock_count=table.get("Availability"),
            review_count=table.get("Number of reviews"),
            category=response.css(".breadcrumb a[href*='category/books/']::text").get(),
            description=response.css("#product_description + p::text").get(),
            rating=response.css(".product_main .star-rating::attr(class)").get(),
            source_url=response.url, list_url=list_url, list_page=list_page)
