"""Локальный HTTP-стенд. Ошибки и изменения данных создаются только здесь."""
import gzip
import hashlib
import json
import threading
from collections import Counter
from datetime import datetime,timezone,timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

ROOT=Path(__file__).resolve().parents[1]
HOSTS=['books.toscrape.com','www.scrapingcourse.com','api.worldbank.org']

class FixtureServer:
    def __init__(self,port=0):
        self.counts=Counter();self.phase=1;self.lock=threading.Lock()
        self.data=json.loads((ROOT/'fixtures/records.json').read_text(encoding='utf-8'))
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                parsed=urlsplit(self.path);q=parse_qs(parsed.query)
                host=q.get('host',[self.headers.get('X-Lab-Host','books.toscrape.com')])[0]
                group=q.get('group',['default'])[0]
                with owner.lock:
                    owner.counts[(group,host,parsed.path)]+=1
                    count=owner.counts[(group,host,parsed.path)]
                status=200;headers={};items=None
                if group=='n8n' and host==HOSTS[0] and parsed.path=='/page/1' and count<=2:
                    self.connection.shutdown(2);self.connection.close();return
                if parsed.path=='/health':body=b'{"status":"ok"}'
                elif parsed.path=='/metrics':body=json.dumps([{'group':g,'host':h,'path':p,'requests':n} for (g,h,p),n in owner.counts.items()]).encode()
                elif parsed.path=='/robots.txt':
                    body=b'User-agent: *\nAllow: /\nDisallow: /private/\nCrawl-delay: 0\nSitemap: /manifest\n'
                elif parsed.path=='/manifest':
                    urls=[{'url':f'https://{host}/page/{i}','lastmod':('2026-10-26T01:00:00+00:00' if owner.phase==2 and i<=2 else '2026-10-25T01:00:00+00:00')} for i in range(1,5)]
                    body=json.dumps({'pages':urls}).encode()
                elif parsed.path.startswith('/page/'):
                    page=int(parsed.path.rsplit('/',1)[1]);items=owner.data[host][(page-1)*5:page*5]
                    body=json.dumps({'items':items,'source':host},ensure_ascii=False).encode()
                    if owner.phase==2 and page==1:
                        body=json.dumps({'items':items,'source':host,'revision':2},ensure_ascii=False).encode()
                    etag='"'+hashlib.sha256(body).hexdigest()[:20]+'"';headers={'ETag':etag,'Last-Modified':'Sun, 25 Oct 2026 01:00:00 GMT'}
                    if group in {'A','B'} and host==HOSTS[0] and page==1 and count==1:
                        status=429;body=b'{"error":"slow down"}';headers={'Retry-After':'0.2'}
                    elif self.headers.get('If-None-Match')==etag:
                        status=304;body=b''
                elif parsed.path=='/fault/series':
                    status=503 if count<=3 else 200;body=b'{"items":[{"key":"recovered"}],"ok":true}' if status==200 else b'{"error":"temporary server failure"}'
                elif parsed.path=='/fault/429-number':
                    status=429 if count==1 else 200;headers={'Retry-After':'0.25'};body=b'{"items":[{"key":"number"}],"ok":true}'
                elif parsed.path=='/fault/429-date':
                    status=429 if count==1 else 200
                    headers={'Retry-After':format_datetime(datetime.now(timezone.utc)+timedelta(seconds=1),usegmt=True)}
                    body=b'{"items":[{"key":"date"}],"ok":true}'
                elif parsed.path=='/fault/429-plain':
                    status=429 if count==1 else 200;body=b'{"items":[{"key":"no-header"}],"ok":true}'
                elif parsed.path=='/fault/captcha':body=b'<html><title>Access denied</title><p>captcha verify you are human</p></html>'
                elif parsed.path.startswith('/status/'):
                    status=int(parsed.path.rsplit('/',1)[1]);body=b'{"error":"controlled status response"}'
                else:status=404;body=b'{"error":"not found"}'
                if body and 'gzip' in self.headers.get('Accept-Encoding',''):
                    body=gzip.compress(body,mtime=0);headers['Content-Encoding']='gzip'
                self.send_response(status)
                for k,v in headers.items():self.send_header(k,v)
                self.send_header('Content-Length',str(len(body)));self.send_header('Content-Type','application/json; charset=utf-8')
                self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.port=self.server.server_port
    def __enter__(self):
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join()

if __name__=='__main__':
    with FixtureServer(8768) as fixture:
        print('Local training server: http://127.0.0.1:8768',flush=True)
        try:threading.Event().wait()
        except KeyboardInterrupt:pass
