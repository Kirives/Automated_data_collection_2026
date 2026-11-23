import random
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import requests

def classify(status=None,error=None):
    if isinstance(error,(requests.Timeout,requests.ConnectionError)):return 'network',True
    if error:return 'other_exception',False
    if status==429:return 'rate_limit',True
    if status==401:return 'authentication',False
    if status==403:return 'access_denied',False
    if status is not None and 400<=status<500:return 'client_error',False
    if status is not None and 500<=status<600:return 'server_error',True
    return 'success',False

def retry_after(value,now=None):
    if value is None:return None
    try:return max(0,float(value))
    except (ValueError,TypeError):
        try:
            date=parsedate_to_datetime(value)
            if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
            return max(0,(date-(now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError,TypeError,OverflowError):return None

def delay_for(attempt,header=None,base=.3,cap=3,rng=None):
    parsed=retry_after(header)
    if parsed is not None:return parsed,'Retry-After'
    return (rng or random).uniform(0,min(cap,base*2**(attempt-1))),'backoff'
