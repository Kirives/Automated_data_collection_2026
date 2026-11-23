"""Небольшой контрольный прогон на трёх настоящих источниках прежних работ."""
import json
import re
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from .collect import Collector
from .detector import detect
from .limiter import DomainLease
from .observability import ROOT,save

TARGETS=[('books.toscrape.com','https://books.toscrape.com/catalogue/page-1.html','product_pod'),
 ('www.scrapingcourse.com','https://www.scrapingcourse.com/button-click','product-item'),
 ('api.worldbank.org','https://api.worldbank.org/v2/country/RUS/indicator/SP.POP.TOTL?format=json&date=2020:2022','countryiso3code')]

def parse(host,url,body):
    if host=='api.worldbank.org':
        return [{'key':f"worldbank:{r['countryiso3code']}:{r['date']}",'title':r['country']['value'],'value':str(r['value']),'unit':'persons','source_url':url}
                for r in json.loads(body)[1] if r['value'] is not None]
    soup=BeautifulSoup(body,'html.parser');rows=[]
    cards=soup.select('article.product_pod' if host=='books.toscrape.com' else '#product-grid .product-item')
    for card in cards:
        if host=='books.toscrape.com':
            link=card.select_one('h3 a');title=link.get('title') or link.get_text();price=card.select_one('.price_color').get_text();unit='GBP'
        else:
            link=card.select_one('a[href]');title=card.select_one('.product-name').get_text();price=card.select_one('.product-price').get_text();unit='USD'
        absolute=urljoin(url,link['href'])
        slug=urlsplit(absolute).path.rstrip('/').replace('/index.html','').split('/')[-1]
        rows.append({'key':host+':'+slug,'title':title.strip(),'value':re.sub(r'[^0-9.]','',price),'unit':unit,'source_url':absolute})
    return rows

def main():
    c=Collector('live','B',state_name='live');records=[];checks=[];robots=[]
    try:
        for host,url,marker in TARGETS:
            with DomainLease(ROOT/'state/locks',host):
                try:
                    info=c.prepare(host)
                    info['probe_url']=url;info['can_fetch']=c.robots[host].can_fetch(c.ua,url);robots.append(info)
                    response=c.fetch(url,expected=marker)
                    if response is None:checks.append({'host':host,'error':'Домен недоступен или остановлен'});continue
                    check=detect(response['status'],response['body'],marker)
                    checks.append({'host':host,'status':response['status'],**check,'bytes':len(response['body'])})
                    directory=ROOT/'reports/real_responses';directory.mkdir(exist_ok=True)
                    (directory/(host+'.body')).write_bytes(response['body']);save(directory/(host+'.headers.json'),response['headers'])
                    if response['status']==200 and check['verdict']=='ok':records.extend(parse(host,url,response['body']))
                    if host=='books.toscrape.com' and response['status']==200:
                        cached=c.fetch(url,expected=marker,conditional=True)
                        checks.append({'host':host,'conditional_status':cached['status'] if cached else None})
                except Exception as error:
                    c.journal.log('live_error',host=host,url=url,error=type(error).__name__+': '+str(error));checks.append({'host':host,'error':str(error)})
        report=c.journal.report(records);report.update({'fixture':False,'user_agent':c.ua,'contact_configured':bool(c.contact)})
        save(ROOT/'reports/live.json',report);save(ROOT/'reports/live_records.json',records)
        save(ROOT/'reports/live_detection.json',checks);save(ROOT/'reports/live_robots.json',robots)
        print(json.dumps({'records':len(records),'checks':checks,'contact_configured':bool(c.contact)},ensure_ascii=False))
        return 2 if c.blocked or len(robots)!=3 or any('error' in check or check.get('verdict') in {'block', 'suspicion'} for check in checks) or not records else 0
    finally:c.close()

if __name__=='__main__':raise SystemExit(main())
