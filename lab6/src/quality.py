from datetime import datetime,timezone
from collections import Counter
from .contract import Record

def quality(rows, raw_count, rejects, previous_count, raw_contract_valid, checked_at=None):
    checked_at=checked_at or datetime.now(timezone.utc)
    count=len(rows);required=['business_key','source','title','value','unit','source_url','collected_at']
    required_rate=sum(r.get(f) not in [None,''] for r in rows for f in required)/(count*len(required)) if count else 0
    optional=[r.get('category') not in [None,''] for r in rows if r['kind']=='book']
    optional_rate=sum(optional)/len(optional) if optional else 1
    rules=sum(bool(Record.model_validate(r)) for r in rows)/count if count else 0
    rejected_rows=len({r['row'] for r in rejects if 'row' in r and r['stage']!='5. Дубликаты'})
    duplicates=len({r['row'] for r in rejects if r['stage']=='5. Дубликаты'})
    age=max(((checked_at-r['collected_at']).total_seconds()/86400 for r in rows),default=999)
    difference=abs(count-previous_count)/previous_count if previous_count else 0
    specs=[('Полнота обязательных',required_rate,1,.99,True,'Обязательные поля нужны всем представлениям'),
        ('Полнота необязательных',optional_rate,.95,.8,True,'Категория оценивается только у книг, к API неприменима'),
        ('Уникальность ключей',len({r['business_key'] for r in rows})/count if count else 0,1,.99,True,'Дубли искажают агрегаты'),
        ('Валидность от raw',raw_contract_valid/raw_count if raw_count else 0,.95,.90,True,'Контракт проверяется до удаления повторов; повтор может быть валидным'),
        ('Доля невалидных строк',rejected_rows/raw_count if raw_count else 1,.05,.10,False,'Отбраковка по типам/правилам; удаления повторов считаются отдельно'),
        ('Доля удаления повторов',duplicates/raw_count if raw_count else 1,.10,.50,False,'Повторная доставка допустима, но более 10% требует внимания; выше 50% блокирует mart'),
        ('Согласованность правил',rules,1,.99,True,'Ключ, единицы и предметные диапазоны должны совпадать'),
        ('Возраст данных, дней',age,7,30,False,'Возраст с момента получения, год наблюдения хранится отдельно'),
        ('Изменение объёма',difference,.10,.20,False,'Падение более 20% требует остановки')]
    metrics=[]
    for name,value,green,yellow,higher,note in specs:
        status=('green' if value>=green else 'yellow' if value>=yellow else 'red') if higher else ('green' if value<=green else 'yellow' if value<=yellow else 'red')
        metrics.append({'metric':name,'value':round(value,6),'green':green,'yellow':yellow,'direction':'>=' if higher else '<=','status':status,'reason':note})
    overall=max((m['status'] for m in metrics),key={'green':0,'yellow':1,'red':2}.get)
    return {'checked_at':checked_at.isoformat(),'records':count,'raw_records':raw_count,'previous_records':previous_count,
        'metrics':metrics,'status':overall,'rejected_invalid':rejected_rows,'removed_duplicates':duplicates,
        'total_removed_fraction':len({r['row'] for r in rejects if 'row' in r})/raw_count,
        'contract_valid_raw':raw_contract_valid,'reject_reasons':dict(Counter(r['reason'] for r in rejects))}

def gate_mart(report):
    bad=[r['metric'] for r in report['metrics'] if r['status']=='red']
    if bad:raise RuntimeError('Загрузка mart остановлена: '+', '.join(bad))
