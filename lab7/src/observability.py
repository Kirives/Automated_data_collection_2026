import json
import statistics
import threading
import time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

class Journal:
    def __init__(self,run_id):
        self.run_id=run_id;self.path=ROOT/'logs'/f'run_{run_id}.jsonl';self.path.parent.mkdir(exist_ok=True)
        if self.path.exists():
            archive=self.path.parent/'archive';archive.mkdir(exist_ok=True)
            self.path.replace(archive/(str(time.time_ns())+'_'+self.path.name))
        self.events=[];self.lock=threading.Lock();self.started=time.perf_counter()
    def log(self,event,**fields):
        item={'ts':datetime.now(timezone.utc).isoformat(),'run_id':self.run_id,'event':event,
              'host':'','url':'','status':None,'ms':0,'attempt':0,'bytes':0,'error':None,**fields}
        with self.lock:
            self.events.append(item)
            with self.path.open('a',encoding='utf-8') as file:file.write(json.dumps(item,ensure_ascii=False,default=str)+'\n')
        return item
    def report(self,records,rejected=0):
        requests=[r for r in self.events if r['event']=='request'];n=len(requests)
        errors=[r for r in requests if (r['status'] is None or r['status']>=400) and not (r.get('resource')=='robots' and r['status']==404)]
        latencies=[r['ms'] for r in requests];sizes=[r.get('decoded_bytes',r['bytes']) for r in requests if r['status']==200 and r.get('resource')=='data']
        report={'run_id':self.run_id,'requests':n,'codes':dict(Counter(str(r['status']) for r in requests)),
            'error_fraction':len(errors)/n if n else 0,'rate_429_403':sum(r['status'] in {429,403} for r in requests)/n if n else 0,
            'retries':sum(r['attempt']>1 for r in requests),'median_ms':statistics.median(latencies) if latencies else 0,
            'p95_ms':float(np.percentile(latencies,95)) if latencies else 0,'traffic_bytes':sum(r['bytes'] for r in requests),
            'responses_304':sum(r['status']==304 for r in requests),'breaker_activations':sum(r['event']=='breaker_open' for r in self.events),
            'records':len(records),'rejected':rejected,'duration_seconds':time.perf_counter()-self.started,
            'mean_body_bytes':statistics.mean(sizes) if sizes else 0,
            'blocked_domains':sorted({r['host'] for r in self.events if r['event']=='blocked'}),
            'skipped_incremental':sum(r['event']=='incremental_skip' for r in self.events),
            'expected_missing_robots':sum(r.get('resource')=='robots' and r['status']==404 for r in requests)}
        report.update(alerts(report));return report

THRESHOLDS=[('error_fraction',.10,'Ошибок более 10%'),('rate_429_403',.05,'429/403 более 5%'),
            ('p95_ms',3000,'p95 выше 3 секунд'),('breaker_activations',0,'Сработал предохранитель'),
            ('rejected_fraction',.05,'Отброшено более 5% записей'),('empty_result',0,'Пустой результат')]

def alerts(report):
    values={**report,'rejected_fraction':report['rejected']/max(1,report['records']+report['rejected']),
            'empty_result':int(report['records']==0)}
    hits=[{'metric':metric,'value':values[metric],'threshold':limit,'reason':reason} for metric,limit,reason in THRESHOLDS if values[metric]>limit]
    if report['blocked_domains']:hits.append({'metric':'blocked_domains','reason':'Домен остановлен детектором','value':report['blocked_domains']})
    return {'alerts':hits,'status':'red' if hits else 'green'}
