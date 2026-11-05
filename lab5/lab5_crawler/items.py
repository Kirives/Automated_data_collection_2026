import scrapy

class BookItem(scrapy.Item):
    kind = scrapy.Field()
    upc = scrapy.Field()
    title = scrapy.Field()
    price_excl_tax = scrapy.Field()
    stock_count = scrapy.Field()
    review_count = scrapy.Field()
    category = scrapy.Field()
    description = scrapy.Field()
    rating = scrapy.Field()
    source_url = scrapy.Field()
    list_url = scrapy.Field()
    list_page = scrapy.Field()

class QuoteItem(scrapy.Item):
    kind = scrapy.Field()
    quote_id = scrapy.Field()
    quote = scrapy.Field()
    author = scrapy.Field()
    tags = scrapy.Field()
    born_date = scrapy.Field()
    born_location = scrapy.Field()
    biography = scrapy.Field()
    source_url = scrapy.Field()
    list_url = scrapy.Field()
    list_page = scrapy.Field()
