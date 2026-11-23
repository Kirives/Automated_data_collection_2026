"""Общий HTTP-клиент. Сценарии отказа запускаются только на локальном стенде."""
import gzip
import hashlib
import json
import os
import random
import time
from urllib.parse import urlsplit,quote
from urllib.robotparser import RobotFileParser
import requests
from urllib3.util import Timeout
from urllib3.exceptions import HTTPError
from .breaker import CircuitBreaker
from .detector import detect
from .limiter import TokenBucket
from .observability import ROOT,Journal,save
from .retry import classify,delay_for

RATES={'books.toscrape.com':2.0,'www.scrapingcourse.com':1.0,'api.worldbank.org':1.5}
DEFAULT_CONTACT='test@mail.ru'

class Collector:
    def __init__(self,run_id,profile='B',fixture=None,state_name='main',contact=None):
        self.profile=profile;self.fixture=fixture;self.journal=Journal(run_id);self.run_id=run_id
        self.contact=contact or os.environ.get('LAB7_CONTACT') or ('' if fixture else DEFAULT_CONTACT)
        self.ua='VshivkovUniversityLab7/1.0 (educational'+('; contact='+self.contact if self.contact else ('; local-test' if fixture else ''))+')'
        self.sessions={};self.limiters={};self.breakers={};self.robots={};self.blocked=set();self.rng=random.Random(6)
        self.state_path=ROOT/'state'/f'{state_name}_etags.json'
        self.state=json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {}
    def session(self,host):
        if host not in self.sessions:
            session=requests.Session();session.headers.update({'User-Agent':self.ua})
            if self.fixture:session.trust_env=False
            self.sessions[host]=session
            self.limiters[host]=TokenBucket(rate=RATES.get(host,1),burst=1,jitter=.25)
            self.breakers[host]=CircuitBreaker()
        return self.sessions[host]
    def save_state(self):save(self.state_path,self.state)
    def close(self):
        self.save_state()
        for session in self.sessions.values():session.close()
    def prepare(self,host):
        result=self.fetch('https://'+host+'/robots.txt',resource='robots',expected=None)
        parser=RobotFileParser()
        if result and result['status']==200:
            body=result['body'].decode('utf-8',errors='replace');parser.parse(body.splitlines());state='present'
        elif result and result['status']==404:
            body='';parser.parse([]);state='missing_404'
        else:
            self.blocked.add(host);raise RuntimeError('Не удалось проверить robots.txt: '+host)
        delay=parser.crawl_delay(self.ua) or 0;rate=parser.request_rate(self.ua)
        self.limiters[host].crawl_delay=delay
        if rate:self.limiters[host].rate=min(self.limiters[host].rate,rate.requests/rate.seconds)
        self.robots[host]=parser
        info={'host':host,'status':result['status'],'state':state,'crawl_delay':delay,'request_rate':list(rate) if rate else None,
              'sitemaps':parser.site_maps() or [],'configured_rps':RATES.get(host,1),
              'effective_rps':min(self.limiters[host].rate,1/delay) if delay else self.limiters[host].rate}
        # Локальный стенд не заменяет сохранённые правила настоящих сайтов.
        if not self.fixture:
            directory=ROOT/'reports/robots';directory.mkdir(parents=True,exist_ok=True)
            (directory/(host+'.txt')).write_text(body,encoding='utf-8');save(directory/(host+'.json'),info)
        return info
    def fetch(self,url,resource='data',expected='items',conditional=None,encoding=None,max_attempts=None,budget=20):
        host=urlsplit(url).hostname;session=self.session(host);breaker=self.breakers[host]
        if host in self.blocked:
            self.journal.log('domain_skipped',host=host,url=url,error='blocked');return None
        if resource!='robots' and host in self.robots and not self.robots[host].can_fetch(self.ua,url):
            self.journal.log('robots_denied',host=host,url=url,error='Disallow');return None
        conditional=self.profile=='C' if conditional is None else conditional
        encoding=encoding or ('gzip' if self.profile=='C' else 'identity')
        max_attempts=max_attempts or (1 if self.profile=='A' else 3)
        started=time.monotonic()
        for attempt in range(1,max_attempts+1):
            if self.profile!='A':
                old=breaker.state
                if not breaker.allow():
                    self.journal.log('breaker_skip',host=host,url=url,error='open');return None
                if old!=breaker.state:self.journal.log('breaker_half_open',host=host,url=url)
                self.limiters[host].acquire()
            remaining=budget-(time.monotonic()-started)
            if remaining<=0:self.journal.log('budget_exhausted',host=host,url=url,error='URL time budget');return None
            headers={'Accept-Encoding':encoding}
            cached=self.state.get(url,{})
            if conditional:
                if cached.get('etag'):headers['If-None-Match']=cached['etag']
                elif cached.get('last_modified'):headers['If-Modified-Since']=cached['last_modified']
            actual=url
            if self.fixture:
                path=urlsplit(url).path
                actual=f'http://127.0.0.1:{self.fixture.port}{path}?host={quote(host)}&group={quote(self.run_id)}'
            tick=time.perf_counter();error=None;status=None;body=b'';wire=b'';response_headers={}
            try:
                with session.get(actual,headers=headers,timeout=Timeout(total=remaining,connect=min(3,remaining),read=min(8,remaining)),
                                 stream=True,allow_redirects=False) as response:
                    status=response.status_code;response_headers=dict(response.headers)
                    wire=response.raw.read(decode_content=False)
                    body=gzip.decompress(wire) if response.headers.get('Content-Encoding')=='gzip' else wire
            except (requests.RequestException,OSError,EOFError,HTTPError) as exception:
                error=requests.ConnectionError(str(exception)) if isinstance(exception,HTTPError) else exception
            latency=time.perf_counter()-tick
            if self.profile!='A':self.limiters[host].observe(latency,status)
            category,retry=classify(status,error)
            verdict=detect(status,body,expected) if error is None and status!=304 else {'verdict':'ok','reason':''}
            delay,delay_source=(0,'none')
            if retry and attempt<max_attempts and self.profile!='A':delay,delay_source=delay_for(attempt,response_headers.get('Retry-After'),rng=self.rng)
            self.journal.log('request',host=host,url=url,status=status,ms=round(latency*1000,3),attempt=attempt,
                bytes=len(wire),decoded_bytes=len(body),error=type(error).__name__ if error else None,
                error_class=category,delay_seconds=delay,delay_source=delay_source,verdict=verdict['verdict'],
                resource=resource,conditional_sent=any(k.startswith('If-') for k in headers))
            if verdict['verdict']=='block':
                self.blocked.add(host)
                incident=ROOT/'logs/incidents'/f'{self.run_id}_{hashlib.sha256(url.encode()).hexdigest()[:12]}'
                incident.mkdir(parents=True,exist_ok=True)
                (incident/'body.html').write_bytes(body);save(incident/'headers.json',response_headers)
                save(incident/'incident.json',{'url':url,**verdict})
                self.journal.log('blocked',host=host,url=url,status=status,error=verdict['reason']);return None
            if self.profile!='A':
                old=breaker.state
                if retry:breaker.failure()
                elif category=='success':breaker.success()
                if breaker.state=='open' and old!='open':self.journal.log('breaker_open',host=host,url=url)
                if old=='half-open' and breaker.state=='closed':self.journal.log('breaker_closed',host=host,url=url)
            if retry:
                if attempt==max_attempts or self.profile=='A':return None
                if delay>budget-(time.monotonic()-started):
                    self.journal.log('budget_exhausted',host=host,url=url,error='Retry-After превышает оставшийся бюджет');return None
                time.sleep(delay);continue
            if status==401:self.journal.log('authentication_required',host=host,url=url,error='Обновить токен вне автоматического повтора')
            if status==304:
                if 'body' not in cached:self.journal.log('cache_missing',host=host,url=url,error='Нет локального тела для 304');return None
                return {'status':304,'body':cached['body'].encode('utf-8'),'headers':response_headers,'verdict':verdict}
            if status==200 and verdict['verdict']=='ok':
                self.state[url]={'etag':response_headers.get('ETag'),'last_modified':response_headers.get('Last-Modified'),
                                 'body':body.decode('utf-8',errors='replace')}
            return {'status':status,'body':body,'headers':response_headers,'verdict':verdict}
        return None

