import statistics

MARKERS=['captcha','access denied','доступ ограничен','verify you are human']

def detect(status,body,expected=None):
    content=body.decode('utf-8',errors='replace').lower()
    if status==403:return {'verdict':'block','reason':'HTTP 403'}
    for marker in MARKERS:
        if marker in content:return {'verdict':'block','reason':'Маркер: '+marker}
    if status==429:return {'verdict':'suspicion','reason':'HTTP 429: снизить скорость'}
    if status==200 and (len(body)<40 or (expected and expected.lower() not in content)):
        return {'verdict':'suspicion','reason':'Малый ответ или отсутствует ожидаемое содержимое'}
    return {'verdict':'ok','reason':''}

def degradation(current,history):
    findings=[]
    for field,threshold in [('records',.20),('mean_body_bytes',.30)]:
        values=[r[field] for r in history if r.get(field,0)>0]
        if not values:continue
        baseline=statistics.median(values);deviation=abs(current[field]-baseline)/baseline
        if deviation>threshold:findings.append({'metric':field,'median':baseline,'value':current[field],'deviation':deviation,'status':'red'})
    return findings
