"""Guarded follow-up tuning on the disposable submission database only.

Commands: init; control; apply LABEL SQL_PATH; race LABEL [--repeats 3]; verify.
The exact race_test.py is invoked in a separate process without monkeypatching.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
import psycopg2
from psycopg2 import extensions

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from final_verification import fingerprints,checkout_edges
from race_client import linux_address,verify_linux_authentication
LOGS=Path(__file__).parent/'logs'
BASE=LOGS/'flash_followup_baseline.json'
DB='kloudkart_submission_20261127'


def save(path,obj):
    path.write_text(json.dumps(obj,indent=2,default=str)+'\n',encoding='utf-8')


def connect():
    x=json.loads(subprocess.check_output(['docker','inspect','kloudkart_rebuild'],text=True))[0]
    assert x['Name']=='/kloudkart_rebuild' and x['State']['Running']
    env=dict(v.split('=',1) for v in x['Config']['Env'] if '=' in v)
    dsn=extensions.make_dsn(host='127.0.0.1',port=5433,dbname=DB,user='postgres',password=env['POSTGRES_PASSWORD'])
    c=psycopg2.connect(dsn);c.autocommit=True
    expected=subprocess.check_output(['docker','exec','kloudkart_rebuild','psql','-X','-U','postgres','-d',DB,'-qAtc','SELECT system_identifier::text FROM pg_control_system()'],text=True).strip()
    with c.cursor() as cur:
        cur.execute('SELECT current_database(),system_identifier::text FROM pg_control_system()')
        assert cur.fetchone()==(DB,expected),'Wrong disposable database/cluster'
    return c,dsn


def safety(c):
    with c.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM products WHERE product_name LIKE 'RACE TEST FIXTURE%'")
        assert cur.fetchone()[0]==0,'Existing official fixture, refusing wildcard cleanup'
        cur.execute('SELECT MAX(product_id)+1000 FROM products');pid=cur.fetchone()[0]
        for table in ('order_items','inventory_log'):
            cur.execute(f'SELECT COUNT(*) FROM {table} WHERE product_id BETWEEN %s AND %s',(pid,pid+300))
            assert cur.fetchone()[0]==0,'Historical references overlap harness fixture range'


def control(dsn):
    rows=[{} for _ in range(400)];release={}
    barrier=threading.Barrier(400,action=lambda:release.update(at=time.perf_counter()))
    def worker(i):
        c=None
        try:
            t=time.perf_counter();c=psycopg2.connect(dsn);c.autocommit=True
            opened=time.perf_counter();barrier.wait(timeout=60)
            q=time.perf_counter()
            with c.cursor() as cur:cur.execute('SELECT 1');assert cur.fetchone()[0]==1
            rows[i]=dict(connection_ms=(opened-t)*1000,query_ms=(time.perf_counter()-q)*1000)
        except Exception as exc:
            rows[i]=dict(error_type=type(exc).__name__);barrier.abort()
        finally:
            if c is not None:c.close()
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(400)]
    start=time.perf_counter()
    for t in threads:t.start()
    for t in threads:t.join()
    end=time.perf_counter()
    assert all('error_type' not in r for r in rows) and all(rows)
    return dict(total_seconds=end-start,before_barrier_seconds=release['at']-start,
                after_barrier_seconds=end-release['at'],successes=len(rows),errors=0,
                connection_median_ms=statistics.median(r['connection_ms'] for r in rows),
                query_max_ms=max(r['query_ms'] for r in rows))


def linux_run(dsn,control_only=False):
    # Same server and 400 connections; only the client runtime/network path differs.
    target=extensions.make_dsn(dsn,host=linux_address(),port=5432)
    environment=os.environ.copy();environment['DATABASE_URL']=target
    source=ROOT/'tests/phase3/flash_client_control.py' if control_only else ROOT/'race_test.py'
    target_file='/lab/control.py' if control_only else '/lab/race_test.py'
    command=['docker','run','--rm','--network','container:kloudkart_rebuild',
             '--env','DATABASE_URL','--mount',f'type=bind,source={source},target={target_file},readonly',
             'kloudkart-race-client:de03','python',target_file]
    if not control_only:command+=['--test','2','--verbose']
    return subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['init','control','apply','race','verify'])
    ap.add_argument('label',nargs='?',default='baseline')
    ap.add_argument('source',nargs='?')
    ap.add_argument('--repeats',type=int,default=3)
    ap.add_argument('--client',choices=['windows','linux'],default='windows')
    a=ap.parse_args()
    assert re.fullmatch('[a-zA-Z0-9_-]+',a.label)
    c,dsn=connect();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    safety(c)
    if a.client=='linux' and a.command in ('control','race'):
        auth=verify_linux_authentication(dsn)
        assert auth['database']==DB
        save(LOGS/f'flash_auth_{stamp}.json',auth)
        print('PASS Linux bridge route rejects invalid password and accepts correct password',flush=True)
    if a.command=='init':
        assert not BASE.exists(),'Baseline already exists'
        files=[ROOT/'schema.sql',ROOT/'load.sql',ROOT/'race_test.py',*sorted((ROOT/'data').glob('*.csv'))]
        with c.cursor() as cur:
            cur.execute("SELECT pg_get_functiondef('public.place_order(bigint,bigint,integer)'::regprocedure)")
            definition=cur.fetchone()[0]
        (LOGS/'flash_followup_original.sql').write_text(definition,encoding='utf-8')
        save(BASE,dict(fingerprints=fingerprints(c),file_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                       git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))
        print('PASS follow-up baseline and rollback definition saved',flush=True)
        c.close();return
    baseline=json.loads(BASE.read_text())
    assert fingerprints(c)==baseline['fingerprints'],'Historical tables differ before trial'
    if a.command=='control':
        c.close();records=[]
        for n in range(a.repeats):
            if a.client=='linux':
                p=linux_run(dsn,control_only=True)
                assert p.returncode==0,'Linux control failed'
                row=json.loads(p.stdout)
            else:row=control(dsn)
            row['client']=a.client;records.append(row)
            save(LOGS/f'flash_control_{a.client}_{stamp}.json',records)
            print(json.dumps(row),flush=True)
        return
    if a.command=='apply':
        source=(ROOT/a.source).read_text(encoding='utf-8-sig')
        with c.cursor() as cur:
            cur.execute(source)
        checks=checkout_edges(c)
        assert fingerprints(c)==baseline['fingerprints']
        save(LOGS/f'flash_apply_{a.label}_{stamp}.json',dict(source=a.source,edge_checks=checks))
        print(f'PASS applied {a.label} and {len(checks)} rollback-only edge checks',flush=True)
    elif a.command=='race':
        c.close();records=[]
        env=os.environ.copy();env['DATABASE_URL']=dsn;env['PYTHONIOENCODING']='utf-8'
        for n in range(1,a.repeats+1):
            p=linux_run(dsn) if a.client=='linux' else subprocess.run([sys.executable,str(ROOT/'race_test.py'),'--test','2','--verbose'],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
            output=p.stdout+p.stderr
            name=f'flash_{a.client}_{a.label}_{stamp}_{n}.log';(LOGS/name).write_text(output,encoding='utf-8')
            m=re.search(r'(\d+) sold, (\d+) refused, (\d+) errored, wall clock ([\d.]+)s',output)
            assert p.returncode==0 and 'PASSED' in output and m,'Official correctness failed'
            assert tuple(int(m[i]) for i in [1,2,3])==(50,350,0)
            row=dict(run=n,client=a.client,successes=50,refusals=350,errors=0,seconds=float(m[4]),log=name)
            records.append(row);save(LOGS/f'flash_{a.client}_{a.label}_{stamp}_results.json',records)
            print(json.dumps(row),flush=True)
        c,_=connect();safety(c)
        assert fingerprints(c)==baseline['fingerprints'],'Harness cleanup changed historical data'
        print(json.dumps(dict(median=statistics.median(r['seconds'] for r in records),worst=max(r['seconds'] for r in records),all_under_ten=all(r['seconds']<=10 for r in records))),flush=True)
    elif a.command=='verify':
        assert fingerprints(c)==baseline['fingerprints']
        for name,digest in baseline['file_sha256'].items():
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
        assert baseline['git_head']==subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        print('PASS historical records, original files, CSVs and Git HEAD preserved',flush=True)
    c.close()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(f'FAILED {type(exc).__name__}; SQLSTATE={getattr(exc,"pgcode",None)}',flush=True)
        raise SystemExit(1) from None
