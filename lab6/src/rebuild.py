import argparse
import hashlib
import json
import statistics
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .common import ROOT, read_jsonl, write_jsonl, save, raw_hashes, dumps, read_result
from .clean import clean_rows,contract_demo
from .quality import quality,gate_mart
from db.load import connect,upsert,constraint_demo

def dataframe(rows):
    frame=pd.DataFrame(rows)
    for name in ['stock','rating','year','status']:frame[name]=frame[name].astype('Int64')
    frame['collected_at']=pd.to_datetime(frame['collected_at'],utc=True)
    return frame

def save_parquet(frame,path):
    table=pa.Table.from_pandas(frame,preserve_index=False)
    if 'value' in table.column_names:
        i=table.column_names.index('value');table=table.set_column(i,'value',table['value'].cast(pa.decimal128(14,2)))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pq.write_table(table,path,compression='snappy')

def benchmark(frame):
    folder=ROOT/'clean/formats';folder.mkdir(exist_ok=True)
    bench=frame.copy();bench['code']=[f'{i:06d}' for i in range(1,len(bench)+1)]
    bench.to_csv(folder/'dataset.csv',index=False,encoding='utf-8')
    write_jsonl(folder/'dataset.jsonl',bench.to_dict('records'))
    save_parquet(bench,folder/'dataset.parquet')
    readers={
        'CSV':lambda cols=None:pd.read_csv(folder/'dataset.csv',usecols=cols),
        'JSONL':lambda cols=None:pd.read_json(folder/'dataset.jsonl',lines=True).loc[:,cols] if cols else pd.read_json(folder/'dataset.jsonl',lines=True),
        'Parquet':lambda cols=None:pd.read_parquet(folder/'dataset.parquet',columns=cols)}
    result=[]
    for name,read in readers.items():
        timings=[];partial=[]
        for _ in range(5):
            start=time.perf_counter();full=read();timings.append((time.perf_counter()-start)*1000)
            start=time.perf_counter();read(['title','value','collected_at']);partial.append((time.perf_counter()-start)*1000)
        path=folder/('dataset.'+{'CSV':'csv','JSONL':'jsonl','Parquet':'parquet'}[name])
        result.append({'format':name,'rows':len(full),'bytes':path.stat().st_size,'full_read_ms':round(statistics.median(timings),3),
            'three_columns_ms':round(statistics.median(partial),3),'date_type':str(full.collected_at.dtype),
            'value_python_type':type(full.value.iloc[0]).__name__,'code_type':str(full.code.dtype),'first_code':str(full.code.iloc[0])})
    pd.DataFrame(result).to_csv(ROOT/'clean/format_benchmark.csv',index=False,encoding='utf-8-sig')
    # Корректное чтение текстовых форматов также воспроизводимо.
    corrected=pd.read_csv(folder/'dataset.csv',dtype={'code':'string','value':'string'},parse_dates=['collected_at'])
    assert corrected.code.iloc[0]=='000001'
    save(ROOT/'clean/format_types.json',{'parquet_schema':str(pq.read_schema(folder/'dataset.parquet')),
        'csv_explicit_code':corrected.code.iloc[0],'note':'Для CSV и JSONL нужны явные типы; деньги из текста преобразуются через Decimal.'})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--demo-db',action='store_true');args=parser.parse_args()
    for name in ['clean','mart/views','mart/snapshots','db','artifacts','nocode']:(ROOT/name).mkdir(parents=True,exist_ok=True)
    hashes=raw_hashes();manifest=json.loads((ROOT/'raw/manifest.json').read_text(encoding='utf-8'))
    if hashes!=manifest['sha256']:raise RuntimeError('Изменён сырой слой')
    raw=[r for path in sorted((ROOT/'raw').glob('*.jsonl')) for r in read_jsonl(path)]
    rows,rejects,protocol,diagnostics=clean_rows(raw);frame=dataframe(rows)
    assert len(rows)>=300 and len({r['source'] for r in rows})>=2
    save_parquet(frame,ROOT/'clean/dataset.parquet')
    write_jsonl(ROOT/'clean/rejects.jsonl',rejects)
    pd.DataFrame(protocol).to_csv(ROOT/'clean/cleaning_protocol.csv',index=False,encoding='utf-8-sig')
    probes=contract_demo(rows);save(ROOT/'clean/contract_checks.json',probes)
    benchmark(frame)
    previous_path=ROOT/'clean/previous_run.json'
    previous=read_result('clean/previous_run.json', {'records': len(rows)})['records']
    report=quality(rows,len(raw),rejects,previous,diagnostics['raw_contract_valid']);save(ROOT/'clean/quality.json',report)
    gate_mart(report)
    connection=connect(ROOT/'db/warehouse.db')
    demo_rejects=[{'stage':'contract_demo','field':r['field'],'reason':r['message'],'payload':r['payload']} for r in probes]
    load_result=upsert(connection,rows,rejects+demo_rejects)
    save(ROOT/'clean/load_result.json',load_result)
    save(ROOT/'clean/database_checks.json',constraint_demo(connection))
    for view in ['by_source','population_by_year','top_books']:
        pd.read_sql_query('SELECT * FROM '+view,connection).to_parquet(ROOT/f'mart/views/{view}.parquet',index=False)
    for date,group in frame.groupby(frame.collected_at.dt.strftime('%Y-%m-%d')):
        save_parquet(group,ROOT/f'mart/snapshots/dt={date}/part-000.parquet')
    partition=next((ROOT/'mart/snapshots').glob('dt=*/part-000.parquet'))
    save(ROOT/'mart/partition_read.json',{'file':partition.relative_to(ROOT).as_posix(),'rows_read':len(pd.read_parquet(partition))})
    if args.demo_db:
        # Тестовые изменения хранятся в отдельной демонстрационной БД.
        demo_path=ROOT/'db/idempotency_demo.db'
        if demo_path.exists():
            archive=ROOT/'db/archive';archive.mkdir(exist_ok=True)
            demo_path.replace(archive/f'idempotency_{time.time_ns()}.db')
        demo=connect(demo_path);results=[]
        results.append({'run':'1. Исходный',**upsert(demo,rows)})
        before=dict(demo.execute('SELECT business_key,updated_at FROM records'))
        results.append({'run':'2. Повторный',**upsert(demo,rows)})
        assert before==dict(demo.execute('SELECT business_key,updated_at FROM records'))
        changed=deepcopy(rows)
        for index in [0,1]:changed[index]['value']+=Decimal('1.00')
        results.append({'run':'3. Две тестовые цены',**upsert(demo,changed)})
        after=dict(demo.execute('SELECT business_key,updated_at FROM records'))
        assert sum(before[k]!=after[k] for k in before)==2 and results[-1]['changed']==2
        for r in results:r.pop('changed_keys')
        save(ROOT/'clean/idempotency.json',results)
        pd.read_sql_query('SELECT * FROM history WHERE business_key IN (?,?)',demo,params=[rows[0]['business_key'],rows[1]['business_key']]).to_csv(ROOT/'clean/history_demo.csv',index=False)
        demo.close()
    save(previous_path,{'records':len(rows),'checked_at':report['checked_at']})
    assert hashes==raw_hashes()
    signature=hashlib.sha256(dumps(rows).encode()).hexdigest()
    proof={'raw_sha256_before':hashes,'raw_sha256_after':raw_hashes(),'clean_logical_sha256':signature,
           'records':len(rows),'offline':True,'network_requests':0}
    save(ROOT/'clean/rebuild_proof.json',proof)
    damaged=deepcopy(report);damaged['metrics'][0]['status']='red'
    try:gate_mart(damaged)
    except RuntimeError as error:save(ROOT/'clean/red_gate_demo.json',{'blocked':True,'message':str(error)})
    connection.close()
    print(dumps({'records':len(rows),'raw':len(raw),'rejects':len(rejects),'quality':report['status'],'sources':frame.source.value_counts().to_dict()}))

if __name__=='__main__':main()
