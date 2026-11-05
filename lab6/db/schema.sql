PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS records (
 business_key TEXT PRIMARY KEY NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('books','worldbank')),
 kind TEXT NOT NULL CHECK(kind IN ('book','population')),
 source_id TEXT NOT NULL,
 title TEXT NOT NULL CHECK(length(trim(title))>=2),
 value_minor INTEGER NOT NULL CHECK(typeof(value_minor)='integer' AND value_minor>0 AND value_minor<=200000000000),
 unit TEXT NOT NULL CHECK(unit IN ('GBP','persons')),
 stock INTEGER CHECK(stock IS NULL OR stock>=0),
 rating INTEGER CHECK(rating IS NULL OR rating BETWEEN 1 AND 5),
 category TEXT,
 year INTEGER CHECK(year IS NULL OR year BETWEEN 1960 AND 2100),
 country_code TEXT,
 source_url TEXT NOT NULL CHECK(source_url LIKE 'https://%'),
 parser_version TEXT NOT NULL,
 collected_at TEXT NOT NULL CHECK(collected_at LIKE '%+00:00'),
 updated_at TEXT NOT NULL CHECK(updated_at LIKE '%+00:00'),
 content_hash TEXT NOT NULL,
 UNIQUE(source,source_id),
 CHECK((kind='book' AND source='books' AND unit='GBP' AND stock IS NOT NULL AND rating IS NOT NULL AND value_minor<=1000000)
    OR (kind='population' AND source='worldbank' AND unit='persons' AND year IS NOT NULL AND length(country_code)=3 AND value_minor%100=0 AND stock IS NULL AND rating IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_source_category ON records(source,category);
CREATE INDEX IF NOT EXISTS idx_country_year ON records(country_code,year);
CREATE INDEX IF NOT EXISTS idx_source_value ON records(source,value_minor DESC);
CREATE TABLE IF NOT EXISTS history (
 business_key TEXT NOT NULL REFERENCES records(business_key),
 version_at TEXT NOT NULL,
 value_minor INTEGER NOT NULL,
 content_hash TEXT NOT NULL,
 payload TEXT NOT NULL,
 PRIMARY KEY(business_key,version_at)
);
CREATE TABLE IF NOT EXISTS rejects (
 reject_id TEXT PRIMARY KEY, stage TEXT NOT NULL, field TEXT NOT NULL,
 reason TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE VIEW IF NOT EXISTS by_source AS
 SELECT source,unit,count(*) AS records,min(value_minor) AS min_value_minor,max(value_minor) AS max_value_minor
 FROM records GROUP BY source,unit;
CREATE VIEW IF NOT EXISTS population_by_year AS
 SELECT year,count(*) AS countries,sum(value_minor)/100 AS population_total
 FROM records WHERE kind='population' GROUP BY year;
CREATE VIEW IF NOT EXISTS top_books AS
 SELECT title,category,value_minor,rating FROM records WHERE kind='book' ORDER BY value_minor DESC LIMIT 10;
