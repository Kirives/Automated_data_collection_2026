import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

REQUIRED = {
    'book': ['upc', 'title', 'price_excl_tax', 'stock_count', 'review_count', 'category', 'description', 'source_url'],
    'quote': ['quote', 'author', 'tags', 'born_date', 'born_location', 'biography', 'source_url'],
}

class PipelineBase:
    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

class ValidatePipeline(PipelineBase):
    def process_item(self, item):
        data = ItemAdapter(item)
        for key in REQUIRED[data['kind']]:
            value = data.get(key)
            if value is None or value == [] or (isinstance(value, str) and not value.strip()):
                self.crawler.stats.inc_value('dropped/missing_fields')
                self.crawler.stats.inc_value('dropped/missing/' + key)
                raise DropItem('Не заполнено поле: ' + key)
        self.crawler.stats.inc_value('pipeline/validated')
        return item

class CleanPipeline(PipelineBase):
    def process_item(self, item):
        data = ItemAdapter(item)
        for key, value in list(data.items()):
            if isinstance(value, str):
                data[key] = re.sub(r'\s+', ' ', value).strip()
        field = 'list_page'
        try:
            data['list_page'] = int(data['list_page'])
            if data['kind'] == 'book':
                data['upc'] = data['upc'].lower()
                field = 'price_excl_tax'
                price = float(data[field].replace('£', '').strip())
                if not math.isfinite(price) or price < 0:
                    raise ValueError('Цена должна быть неотрицательной')
                data[field] = price
                field = 'stock_count'
                match = re.search(r'(\d+)\s+available', data[field])
                if not match:
                    raise ValueError('Не найден остаток')
                data[field] = int(match.group(1))
                field = 'review_count'
                data[field] = int(data[field])
                if data[field] < 0:
                    raise ValueError('Отрицательное число отзывов')
                ratings = {'One': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5}
                data['rating'] = next((value for key, value in ratings.items()
                                       if key in (data.get('rating') or '').split()), None)
            else:
                field = 'born_date'
                data[field] = datetime.strptime(data[field], '%B %d, %Y').date().isoformat()
                field = 'tags'
                data[field] = sorted({tag.strip().lower() for tag in data.get(field, []) if tag.strip()})
                key = data['author'].casefold() + '\0' + data['quote']
                data['quote_id'] = hashlib.sha256(key.encode('utf-8')).hexdigest()
        except (ValueError, TypeError, KeyError) as error:
            self.crawler.stats.inc_value('dropped/invalid_value')
            self.crawler.stats.inc_value('dropped/invalid/' + field)
            raise DropItem(f'Неверный формат {field}: {error}') from error
        self.crawler.stats.inc_value('pipeline/cleaned')
        return item

class DeduplicatePipeline(PipelineBase):
    def open_spider(self):
        self.seen = set()

    def process_item(self, item):
        data = ItemAdapter(item)
        key = ('book', data['upc']) if data['kind'] == 'book' else ('quote', data['author'].casefold(), data['quote'])
        if key in self.seen:
            self.crawler.stats.inc_value('dropped/duplicate_business_key')
            raise DropItem('Повтор бизнес-ключа')
        self.seen.add(key)
        self.crawler.stats.inc_value('pipeline/unique')
        return item

class DatabasePipeline(PipelineBase):
    fields = {
        'books': ['upc', 'title', 'price_excl_tax', 'stock_count', 'review_count', 'category', 'description', 'rating', 'source_url', 'list_url', 'list_page'],
        'quotes': ['quote_id', 'quote', 'author', 'tags', 'born_date', 'born_location', 'biography', 'source_url', 'list_url', 'list_page'],
    }

    def open_spider(self):
        path = Path(self.crawler.settings.get('DATABASE_PATH'))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=15)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS books (
                upc TEXT PRIMARY KEY, title TEXT NOT NULL, price_excl_tax REAL NOT NULL,
                stock_count INTEGER NOT NULL, review_count INTEGER NOT NULL,
                category TEXT NOT NULL, description TEXT NOT NULL, rating INTEGER,
                source_url TEXT NOT NULL, list_url TEXT, list_page INTEGER, last_seen_run TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS quotes (
                quote_id TEXT PRIMARY KEY, quote TEXT NOT NULL, author TEXT NOT NULL, tags TEXT,
                born_date TEXT NOT NULL, born_location TEXT NOT NULL, biography TEXT NOT NULL,
                source_url TEXT NOT NULL, list_url TEXT, list_page INTEGER, last_seen_run TEXT NOT NULL,
                UNIQUE(author, quote));
        ''')
        self.buffers = {'books': [], 'quotes': []}
        self.batch_size = self.crawler.settings.getint('DATABASE_BATCH_SIZE', 25)

    def process_item(self, item):
        data = ItemAdapter(item).asdict()
        table = 'books' if data['kind'] == 'book' else 'quotes'
        if table == 'quotes':
            data['tags'] = json.dumps(data['tags'], ensure_ascii=False)
        values = tuple(data.get(key) for key in self.fields[table]) + (self.crawler.spider.run_id,)
        self.buffers[table].append(values)
        if len(self.buffers[table]) >= self.batch_size:
            self.flush(table)
        return item

    def flush(self, table):
        rows = self.buffers[table]
        if not rows:
            return
        fields = self.fields[table] + ['last_seen_run']
        updates = ', '.join(f'{key}=excluded.{key}' for key in fields[1:])
        sql = f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT({fields[0]}) DO UPDATE SET {updates}"
        try:
            self.connection.executemany(sql, rows)
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            self.crawler.stats.inc_value('database/errors')
            raise
        self.crawler.stats.inc_value('database/batches')
        self.crawler.stats.inc_value('database/written', len(rows))
        self.crawler.stats.inc_value('database/written/' + table, len(rows))
        rows.clear()

    def close_spider(self):
        try:
            for table in self.buffers:
                self.flush(table)
        finally:
            self.connection.close()
