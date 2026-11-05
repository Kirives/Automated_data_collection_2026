import hashlib
import sqlite3
from pathlib import Path
from src.common import ROOT, utcnow, dumps

FIELDS=['business_key','source','kind','source_id','title','value_minor','unit','stock','rating','category','year',
        'country_code','source_url','parser_version','collected_at','updated_at','content_hash']

def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(path)
    connection.executescript((ROOT/'db/schema.sql').read_text(encoding='utf-8'))
    return connection

def upsert(connection, rows, rejects=()):
    stamp=utcnow();existing=dict(connection.execute('SELECT business_key,content_hash FROM records'))
    values=[];snapshots=[];changed=[]
    for row in rows:
        payload={k:v for k,v in row.items() if k!='status'}
        digest=hashlib.sha256(dumps(payload).encode()).hexdigest()
        data={**payload,'value_minor':int(row['value']*100),'updated_at':stamp,'content_hash':digest}
        values.append(tuple(data[k].isoformat() if hasattr(data[k],'isoformat') else data[k] for k in FIELDS))
        if existing.get(row['business_key'])!=digest:
            changed.append(row['business_key'])
            snapshots.append((row['business_key'],stamp,data['value_minor'],digest,dumps(payload)))
    assignments=','.join(f'{f}=excluded.{f}' for f in FIELDS if f!='business_key')
    sql=f"INSERT INTO records ({','.join(FIELDS)}) VALUES ({','.join('?' for _ in FIELDS)}) ON CONFLICT(business_key) DO UPDATE SET {assignments} WHERE records.content_hash<>excluded.content_hash"
    with connection:
        connection.executemany(sql,values)
        connection.executemany('INSERT INTO history VALUES (?,?,?,?,?)',snapshots)
        connection.executemany('INSERT INTO rejects VALUES (?,?,?,?,?) ON CONFLICT(reject_id) DO NOTHING',[
            (hashlib.sha256(dumps(r).encode()).hexdigest(),r['stage'],r['field'],r['reason'],dumps(r['payload'])) for r in rejects])
    return {'rows':connection.execute('SELECT count(*) FROM records').fetchone()[0],'changed':len(changed),
            'changed_keys':changed,'history_rows':connection.execute('SELECT count(*) FROM history').fetchone()[0],'loaded_at':stamp}

def constraint_demo(connection):
    row=connection.execute('SELECT * FROM records LIMIT 1').fetchone();results=[]
    for name,patch in [('CHECK отрицательного значения',{'business_key':'test:check','source_id':'testcheck','value_minor':-100}),('Дубликат ключа',{})]:
        data=dict(zip(FIELDS,row));data.update(patch)
        connection.execute('SAVEPOINT probe')
        try:
            connection.execute(f"INSERT INTO records VALUES ({','.join('?' for _ in FIELDS)})",[data[k] for k in FIELDS])
        except sqlite3.IntegrityError as error:results.append({'check':name,'result':'отклонено','message':str(error)})
        else:raise AssertionError('БД приняла недопустимую строку')
        finally:connection.execute('ROLLBACK TO probe');connection.execute('RELEASE probe')
    return results
