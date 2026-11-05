"""Шесть последовательных шагов. Любое удаление попадает в rejects."""
import re
import unicodedata
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from pydantic import ValidationError
from .common import dumps
from .contract import Record

def text(value):
    if not isinstance(value,str):return value
    value=unicodedata.normalize('NFKC',value)
    return re.sub(r'\s+',' ',re.sub('[\u200b\u200c\u200d\ufeff]','',value)).strip()

def normalize_url(url):
    p=urlsplit(url)
    query=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in {'fbclid','gclid'}]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urlencode(sorted(query)),''))

def clean_rows(raw):
    rows=[]; rejects=[]; protocol=[]
    for i,r in enumerate(raw):
        if r['_kind']=='book':
            row=dict(source_id=r['upc_raw'],title=r['title_raw'],value=r['price_raw'],stock=r['stock_raw'],
                     rating=r['rating_raw'],category=r['category_raw'],year=None,country_code=None,unit='GBP')
        else:
            p=r['payload'];row=dict(source_id=f"{p['countryiso3code']}:{p['date']}",title=p['country']['value'],
                value=p['value'],stock=None,rating=None,category=None,year=p['date'],country_code=p['countryiso3code'],unit='persons')
        row.update(source=r['_source'],kind=r['_kind'],source_url=r['_source_url'],collected_at=r['_collected_at'],
                   parser_version=r['_parser_version'],status=r['_status'],_raw=r,_row=i,_parse_errors=[])
        rows.append(row)
    def reject(row,stage,field,reason):
        rejects.append({'row':row['_row'],'stage':stage,'field':field,'reason':reason,'payload':row['_raw']})
    def step(name,before,changed,note):
        protocol.append({'step':name,'before':before,'after':len(rows),'changed':changed,'removed':before-len(rows),'note':note})
    before=len(rows);changed=0
    for row in rows:
        old=dumps({k:v for k,v in row.items() if not k.startswith('_')})
        for k,v in row.items():
            if not k.startswith('_'):row[k]=text(v)
        changed+=old!=dumps({k:v for k,v in row.items() if not k.startswith('_')})
    step('1. Нормализация текста',before,changed,'NFKC, NBSP, zero-width, пробелы')
    changed=0
    for row in rows:
        old=row['source_url'];row['source_url']=normalize_url(old)
        row['source_id']=row['source_id'].lower() if row['kind']=='book' else row['source_id']
        row['business_key']='books:'+row['source_id'] if row['kind']=='book' else f"worldbank:{row['country_code']}:SP.POP.TOTL:{row['year']}"
        changed+=1
    step('2. Бизнес-ключ',len(rows),changed,'UPC / ISO3 + показатель + год; URL без трекинга')
    changed=0
    for row in rows:
        old=dumps(row)
        for key in ['value','stock','rating','year','collected_at']:
            value=row[key]
            if value is None or value=='':row[key]=None;continue
            try:
                if key=='value':
                    cleaned=re.sub(r'[£,\s]','',str(value))
                    row[key]=Decimal(cleaned).quantize(Decimal('.01'))
                    if not row[key].is_finite():raise ValueError('Не конечное число')
                elif key=='stock':
                    m=re.search(r'(-?\d+) available',str(value));row[key]=int(m[1]) if m else int(value)
                elif key=='rating':
                    names={'One':1,'Two':2,'Three':3,'Four':4,'Five':5}
                    row[key]=next((n for word,n in names.items() if word in str(value).split()),None)
                    if row[key] is None:raise ValueError('Рейтинг не распознан')
                elif key=='year':row[key]=int(value)
                else:row[key]=datetime.fromisoformat(value)
            except (ValueError,TypeError,InvalidOperation):
                row['_parse_errors'].append(key);row[key]=None
        changed+=old!=dumps(row)
    step('3. Типизация',len(rows),changed,'Decimal(14,2), целые, datetime с UTC; ошибки не скрываются')
    raw_contract_valid=0
    for candidate in rows:
        try:Record.model_validate(candidate)
        except ValidationError:pass
        else:raw_contract_valid+=1
    before=len(rows);kept=[]
    required=['business_key','source','title','value','unit','source_url','collected_at']
    for row in rows:
        missing=[k for k in required+(['stock','rating'] if row['kind']=='book' else ['year','country_code']) if row.get(k) in [None,'']]
        if missing or row['_parse_errors']:
            reject(row,'4. Пропуски',','.join(sorted(set(missing+row['_parse_errors']))),'обязательное поле пусто или не удалось разобрать тип')
        else:kept.append(row)
    rows=kept;step('4. Пропуски',before,0,'Обязательные → rejects; необязательные → NULL')
    before=len(rows);seen_full=set();seen_key=set();seen_near=set();kept=[]
    for row in sorted(rows,key=lambda r:r['collected_at'],reverse=True):
        full=dumps({k:v for k,v in row.items() if not k.startswith('_')})
        near=(row['source'],re.sub(r'\W','',row['title'].casefold()),str(row['value']),row['unit'],row['year'],row['country_code'])
        reason='полный дубль' if full in seen_full else ('дубль бизнес-ключа' if row['business_key'] in seen_key else ('почти-дубль' if near in seen_near else None))
        if reason:reject(row,'5. Дубликаты','business_key',reason)
        else:kept.append(row)
        seen_full.add(full);seen_key.add(row['business_key']);seen_near.add(near)
    rows=kept;step('5. Дубликаты',before,0,'Свежая запись; полные, по ключу, нормализованному названию/значению/периоду')
    before=len(rows);kept=[]
    for row in rows:
        try:kept.append(Record.model_validate(row).model_dump())
        except ValidationError as error:
            for e in error.errors():reject(row,'6. Правила и контракт','.'.join(map(str,e['loc'])) or '__model__',e['msg'])
    rows=sorted(kept,key=lambda r:r['business_key'])
    step('6. Бизнес-правила и контракт',before,0,'Цена > 0 и ≤ 10000; UPC; рейтинг 1–5; остаток ≥ 0; ISO3; целое население; единицы/источник/ключ')
    return rows,rejects,protocol,{'raw_contract_valid':raw_contract_valid}

def contract_demo(valid):
    book=next(r for r in valid if r['kind']=='book')
    changes=[('Отрицательная цена',{'value':'-1'}),('Пустое название',{'title':''}),
             ('Рейтинг 8',{'rating':8}),('Остаток -2',{'stock':-2}),
             ('Дата без зоны',{'collected_at':'2026-10-26T10:00:00'}),
             ('Чужой URL',{'source_url':'https://example.org/book'}),('Валюта книги',{'unit':'persons'})]
    result=[]
    for name,patch in changes:
        try:Record.model_validate({**book,**patch})
        except ValidationError as error:
            result.append({'check':name,'result':'отклонено','field':str(error.errors()[0]['loc']),
                           'message':error.errors()[0]['msg'],'payload':{**book,**patch}})
        else:raise AssertionError('Контракт пропустил: '+name)
    return result
