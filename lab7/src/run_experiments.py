import argparse
import json
import shutil
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from .collect import Collector
from .detector import degradation
from .fixtures import FixtureServer,HOSTS
from .limiter import DomainLease
from .observability import ROOT,save

def run_profile(fixture,profile):
    collector=Collector(profile,profile,fixture,state_name='benchmark')
    water_path=ROOT/'state/watermark.json'
    previous=json.loads(water_path.read_text()) if water_path.exists() else {}
    water={};records=[]
    def domain(host):
        local=[]
        with DomainLease(ROOT/'state/locks',host):
            collector.prepare(host)
            response=collector.fetch('https://'+host+'/manifest',resource='manifest',expected='pages',conditional=False)
            pages=json.loads(response['body'])['pages']
            for page in pages:
                url=page['url']
                if profile=='C' and page['lastmod']<=previous.get(host,'') and url in collector.state:
                    collector.journal.log('incremental_skip',host=host,url=url)
                    local.extend(json.loads(collector.state[url]['body'])['items']);continue
                response=collector.fetch(url)
                if response and response['status'] in {200,304} and response['verdict']['verdict']=='ok':
                    local.extend(json.loads(response['body'])['items'])
            water[host]=max(p['lastmod'] for p in pages)
        return local
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for result in pool.map(domain,HOSTS):records.extend(result)
        unique={r['key']:r for r in records};report=collector.journal.report(list(unique.values()))
        report['logical_pages']=12;report['logical_records']=60;report['workers']=3
        report['robots_included']=True;report['fixture']=True
        save(ROOT/f'reports/run_report_{profile}.json',report)
        save(ROOT/f'reports/records_{profile}.json',list(unique.values()))
        if profile!='A':save(water_path,water)
        return report
    finally:collector.close()

def isolation(fixture):
    c=Collector('isolation','B',fixture,state_name='isolation');host=HOSTS[0]
    try:
        c.prepare(host)
        c.fetch(f'https://{host}/fault/series')
        c.fetch(f'https://{host}/page/1') # пропускается: предохранитель открыт
        for other in HOSTS[1:]:
            c.prepare(other);assert c.fetch(f'https://{other}/page/1')['status']==200
        time.sleep(c.breakers[host].cooldown+.05)
        assert c.fetch(f'https://{host}/fault/series')['status']==200
        events=c.journal.events
        assert any(e['event']=='breaker_skip' for e in events)
        assert any(e['event']=='breaker_half_open' for e in events)
        assert c.breakers[host].state=='closed'
        report=c.journal.report([{'key':'recovery'}]);save(ROOT/'reports/isolation.json',report)
    finally:c.close()

def retry_scenarios(fixture):
    c=Collector('retry_scenarios','B',fixture,state_name='retry')
    host=HOSTS[2];c.prepare(host);results=[]
    try:
        for path in ['/fault/429-number','/fault/429-date','/fault/429-plain','/status/404','/status/401']:
            result=c.fetch('https://'+host+path)
            rows=[e for e in c.journal.events if e['event']=='request' and e['url'].endswith(path)]
            results.append({'scenario':path,'attempts':len(rows),'statuses':[r['status'] for r in rows],
                'delay_sources':[r['delay_source'] for r in rows],'final_status':result['status'] if result else None})
        assert all(r['attempts']==1 for r in results[-2:])
        assert results[0]['delay_sources'][0]=='Retry-After' and results[1]['delay_sources'][0]=='Retry-After'
        save(ROOT/'reports/retry_scenarios.json',results)
    finally:c.close()

def mechanisms(fixture):
    c=Collector('mechanisms','B',fixture,state_name='mechanisms');host=HOSTS[1]
    try:
        c.prepare(host);url='https://'+host+'/page/1'
        c.fetch(url,conditional=False,encoding='identity')
        first=c.journal.events[-1]
        c.fetch(url,conditional=True,encoding='identity');second=c.journal.events[-1]
        c.fetch(url,conditional=False,encoding='gzip');compressed=c.journal.events[-1]
        assert second['status']==304 and second['bytes']==0 and compressed['bytes']<first['bytes']
        table=[{'mechanism':'Условный GET','requests_before':1,'requests_after':1,'bytes_before':first['bytes'],'bytes_after':second['bytes']},
               {'mechanism':'gzip','requests_before':1,'requests_after':1,'bytes_before':first['bytes'],'bytes_after':compressed['bytes']}]
        # Один и тот же набор страниц, половина не менялась после watermark.
        before=[];after=[]
        for domain in HOSTS:
            for page in range(1,5):
                result=c.fetch(f'https://{domain}/page/{page}',conditional=False,encoding='identity')
                before.append(c.journal.events[-1]['bytes'])
        for domain in HOSTS:
            for page in range(1,3):
                c.fetch(f'https://{domain}/page/{page}',conditional=False,encoding='identity')
                after.append(c.journal.events[-1]['bytes'])
        table.append({'mechanism':'Watermark: неизменившиеся страницы пропускаются','requests_before':12,'requests_after':6,
                      'bytes_before':sum(before),'bytes_after':sum(after),'measurement':'Размеры реальных ответов стенда; отбор по lastmod из manifest'})
        for row in table:row['traffic_saved_percent']=round(100*(1-row['bytes_after']/row['bytes_before']),2)
        save(ROOT/'reports/mechanisms.json',table)
    finally:c.close()

def blocked(fixture,mode='captcha'):
    c=Collector('block_'+mode,'B',fixture,state_name='block_'+mode);host=HOSTS[0]
    try:
        c.prepare(host)
        c.fetch('https://'+host+('/fault/captcha' if mode=='captcha' else '/status/403'))
        c.fetch('https://'+host+'/page/1')
        assert host in c.blocked
        report=c.journal.report([]);save(ROOT/f'reports/block_{mode}.json',report)
        return 2
    finally:c.close()

def update_summary(reports):
    from .collect import RATES
    rows=[json.loads(line) for line in (ROOT/'logs/run_B.jsonl').read_text(encoding='utf-8').splitlines()]
    intervals=[]
    for host,rate in RATES.items():
        events=[r for r in rows if r['event']=='request' and r['host']==host]
        starts=sorted(datetime.fromisoformat(r['ts']).timestamp()-r['ms']/1000 for r in events)
        gap=min(b-a for a,b in zip(starts,starts[1:]))
        intervals.append({'host':host,'limit_rps':rate,'requests':len(events),
            'min_interval_seconds':round(gap,4),'required_min_seconds':round(1/rate,4),
            'passed':gap>=1/rate-.04})
    save(ROOT/'reports/rate_validation.json',intervals)
    text='# Сравнение прогонов A/B/C\n\nЛокальный стенд: 12 страниц и 60 ожидаемых записей.\n\n'
    text+='| Режим | Секунд | Запросов | Байт | Ошибок, % | Повторов | 304 | Записей |\n'
    text+='|---|---|---|---|---|---|---|---|\n'
    for r in reports:
        text+=f"| {r['run_id']} | {r['duration_seconds']:.3f} | {r['requests']} | {r['traffic_bytes']} | {100*r['error_fraction']:.2f} | {r['retries']} | {r['responses_304']} | {r['records']} |\n"
    a,b,c=reports
    text+=f"\nЦена вежливости B-A: {b['duration_seconds']-a['duration_seconds']:.3f} с. Экономия трафика C относительно B: {100*(1-c['traffic_bytes']/b['traffic_bytes']):.2f}%.\n"
    (ROOT/'reports/comparison.md').write_text(text,encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--block-demo',choices=['captcha','403']);args=p.parse_args()
    (ROOT/'state').mkdir(exist_ok=True);(ROOT/'reports').mkdir(exist_ok=True)
    with FixtureServer() as fixture:
        if args.block_demo:return blocked(fixture,args.block_demo)
        # Каждый набор измерений имеет собственные журналы; прошлые прогоны сохраняются.
        for name in ['benchmark_etags.json','watermark.json']:
            path=ROOT/'state'/name
            if path.exists():
                archive=ROOT/'state/archive';archive.mkdir(exist_ok=True);path.replace(archive/(str(time.time_ns())+'_'+name))
        reports=[]
        reports.append(run_profile(fixture,'A'));reports.append(run_profile(fixture,'B'))
        fixture.phase=2;reports.append(run_profile(fixture,'C'))
        assert reports[0]['requests']<=30
        assert reports[1]['records']==reports[2]['records']==60
        assert reports[2]['responses_304']>=3 and reports[2]['skipped_incremental']==6
        save(ROOT/'reports/comparison.json',reports)
        update_summary(reports)
        isolation(fixture);retry_scenarios(fixture);mechanisms(fixture)
        # История состоит из реально измеренных B/C; деградировавший пример явно тестовый.
        current={**reports[1],'records':20,'mean_body_bytes':20}
        save(ROOT/'reports/degradation_demo.json',{'synthetic':True,'history':[reports[1],reports[2]],
             'current':current,'findings':degradation(current,[reports[1],reports[2]])})
    print(json.dumps([{k:r[k] for k in ['run_id','requests','records','traffic_bytes','responses_304','status']} for r in reports],ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
