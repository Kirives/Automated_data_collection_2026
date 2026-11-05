import json
import sqlite3
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab5_crawler.pipelines import REQUIRED
from quality.smoke_check import compare


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def analyze():
    manifest = read_json(ROOT/'data/run_manifest.json')
    frames, stats, completeness = {}, {}, []
    with sqlite3.connect(ROOT/'data/crawl.db') as db:
        for table, run in manifest.items():
            # Старые строки UPSERT не должны скрывать падение объёма нового прогона.
            frame = pd.read_sql_query(f'SELECT * FROM {table} WHERE last_seen_run = ?', db, params=[run])
            frames[table] = frame
            stats[table] = read_json(ROOT/f'data/stats_{run}.json')
            for field in frame.columns:
                filled = frame[field].notna() & ~frame[field].astype(str).str.strip().isin(['', '[]'])
                completeness.append({'table': table, 'field': field, 'filled_pct': round(100*filled.mean(), 2) if len(frame) else 0})
    total = sum(len(frame) for frame in frames.values())
    missing = sum(value.get('dropped/missing_fields',0) for value in stats.values())
    rejected = sum(value.get('item_dropped_count',0) for value in stats.values())
    empty_rows = 0
    for table, frame in frames.items():
        required = REQUIRED['book' if table == 'books' else 'quote']
        empty_rows += int((frame[required].isna() | frame[required].astype(str).apply(lambda s: s.str.strip().isin(['', '[]']))).any(axis=1).sum())
    snapshot = {'run_ids': manifest, 'records': total,
                'empty_required_pct': round(100*(missing+empty_rows)/max(1,total+rejected),3),
                'empty_required_method': 'Доля записей с пустым обязательным полем: сохранённые строки плюс DropItem missing_fields.'}
    current_path, previous_path = ROOT/'quality/current_snapshot.json', ROOT/'quality/previous_snapshot.json'
    if current_path.exists():
        old = read_json(current_path)
        if old['run_ids'] != manifest:
            write_json(previous_path, old)
    previous = read_json(previous_path) if previous_path.exists() else None
    write_json(current_path,snapshot)
    smoke = compare(snapshot, previous)
    # Это искусственные контрольные примеры, а не предыдущие реальные сборы.
    test_previous = {'records':100, 'empty_required_pct':0}
    examples = {
        'normal':compare({'records':90,'empty_required_pct':0},test_previous),
        'decrease_30_percent':compare({'records':70,'empty_required_pct':0},test_previous),
        'empty_6_percent':compare({'records':100,'empty_required_pct':6},test_previous),
    }
    assert examples['normal']['status']=='OK'
    assert examples['decrease_30_percent']['status']==examples['empty_6_percent']['status']=='WARNING'
    books, quotes = frames['books'], frames['quotes']
    categories = books.groupby('category').agg(books=('upc','size'),avg_price_gbp=('price_excl_tax','mean')).round(2).sort_values('books',ascending=False)
    ratings = books.groupby('rating').size().rename('books')
    authors = quotes.groupby('author').size().rename('quotes').sort_values(ascending=False)
    summary = {
        'smoke_examples':examples,'records':total,'tables':{name:len(frame) for name,frame in frames.items()},
        'unique_keys':{'books':int(books.upc.nunique()),'quotes':int(quotes[['author','quote']].drop_duplicates().shape[0])},
        'empty_required_rows_in_db':empty_rows,'snapshot':snapshot,'smoke':smoke,
        'completeness':completeness,
        'counters':{name:{k:v for k,v in value.items() if k.startswith(('dropped/','pipeline/','database/','retry/','downloader/response_status_count/','source/'))} for name,value in stats.items()},
        'seconds':sum(value['elapsed_time_seconds'] for value in stats.values()),
        'network_requests':sum(value.get('downloader/request_count',0) for value in stats.values()),
        'body_bytes':sum(value.get('traffic/body_bytes',0) for value in stats.values()),
        'download_bytes':sum(value.get('downloader/response_bytes',0) for value in stats.values()),
        'retries':sum(value.get('retry/count',0) for value in stats.values()),
        'categories':categories.reset_index().to_dict('records'),
        'ratings':ratings.reset_index().to_dict('records'),
        'authors':authors.reset_index().to_dict('records'),
    }
    return frames, stats, summary


if __name__ == '__main__':
    _,_,summary=analyze()
    print(json.dumps({key:summary[key] for key in ['records','tables','unique_keys','smoke']},ensure_ascii=False,indent=2))
