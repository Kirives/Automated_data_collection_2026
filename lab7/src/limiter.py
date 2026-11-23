"""Отдельный token bucket на домен; один владелец домена среди процессов."""
import hashlib
import msvcrt
import random
import threading
import time
from pathlib import Path

class DomainLease:
    def __init__(self,folder,host):
        Path(folder).mkdir(parents=True,exist_ok=True)
        self.path=Path(folder)/(hashlib.sha256(host.encode()).hexdigest()+'.lock')
    def __enter__(self):
        self.file=self.path.open('a+b');self.file.seek(0)
        if self.file.read(1)==b'':self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            self.file.close();raise RuntimeError('Этот домен уже обрабатывает другой процесс')
        return self
    def __exit__(self,*args):
        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1);self.file.close()

class TokenBucket:
    def __init__(self,rate=2.0,burst=1,jitter=.25,crawl_delay=0,seed=6):
        if rate<=0 or burst<1:raise ValueError('Некорректные параметры ограничителя')
        self.rate=rate;self.burst=burst;self.jitter=jitter;self.tokens=float(burst)
        self.updated=time.monotonic();self.last_start=None;self.delay=0;self.crawl_delay=crawl_delay
        self.random=random.Random(seed);self.lock=threading.Lock()
    def acquire(self):
        with self.lock:
            now=time.monotonic();self.tokens=min(self.burst,self.tokens+(now-self.updated)*self.rate);self.updated=now
            token_wait=max(0,(1-self.tokens)/self.rate)
            gap=max(self.crawl_delay,self.delay)
            spacing=max(0,(self.last_start or (now-gap))+gap-now)
            wait=max(token_wait,spacing)+self.random.uniform(0,self.jitter/self.rate)
            if wait:time.sleep(wait)
            now=time.monotonic();self.tokens=min(self.burst,self.tokens+(now-self.updated)*self.rate)-1
            self.updated=now;self.last_start=now
            return wait
    def observe(self,latency,status):
        target=min(5.0,max(.05,latency))
        self.delay=min(5.0,max(self.delay*2,1/self.rate)) if status in {429,503} else .7*self.delay+.3*target

