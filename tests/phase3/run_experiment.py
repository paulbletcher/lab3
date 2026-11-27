"""Guarded Phase 3 runner; original race_test.py is always a separate process.

Commands: init; apply LABEL SQL_FILE; suite LABEL [--repeats 3]; verify LABEL.
DATABASE_URL is preferred. If absent, credentials are obtained privately from
docker inspect kloudkart_rebuild and passed only in the child environment.
No port 5432 host connections, monitoring during benchmarks, or Git mutations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
import psycopg2
from psycopg2 import extensions, sql

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
LOGS=HERE/'logs'
KEYS={'customers':'customer_id','categories':'category_id','products':'product_id',
      'orders':'order_id','order_items':'order_item_id','inventory_log':'log_id'}

def write(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str)+'\n',encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def connect():
    dsn=os.environ.get('DATABASE_URL')
    origin='inherited DATABASE_URL'
    if not dsn:
        detail=json.loads(subprocess.check_output(['docker','inspect','kloudkart_rebuild'],text=True))[0]
        env=dict(x.split('=',1) for x in detail['Config']['Env'] if '=' in x)
        dsn=extensions.make_dsn(host='127.0.0.1',port=5433,dbname='postgres',user='postgres',password=env['POSTGRES_PASSWORD'])
        origin='private named-container environment; subprocess only'
    parsed=extensions.parse_dsn(dsn)
    if tuple(parsed.get(k) for k in ('host','port','dbname','user'))!=('127.0.0.1','5433','postgres','postgres'):
        raise RuntimeError('Refusing unexpected database endpoint')
    c=psycopg2.connect(dsn)
    c.autocommit=True
    expected=subprocess.check_output(['docker','exec','kloudkart_rebuild','psql','-X','-U','postgres','-d','postgres','-qAt','-c','SELECT system_identifier::text FROM pg_control_system()'],text=True).strip()
    with c.cursor() as cur:
        cur.execute('SELECT system_identifier::text FROM pg_control_system()')
        if cur.fetchone()[0]!=expected:
            c.close()
            raise RuntimeError('Wrong cluster')
    return c,dsn,origin

def queries(c,path):
    source=re.sub(r'--[^\n]*','',path.read_text(encoding='utf-8'))
    out=[]
    with c.cursor() as cur:
        for statement in source.split(';'):
            if statement.strip():
                cur.execute(statement)
                out.append({'columns':[x.name for x in cur.description],'rows':cur.fetchall()})
    return out

def safety(c):
    result=queries(c,HERE/'verify_integrity.sql')
    if result[1]['rows'][0][0]:
        raise RuntimeError('Fixtures already exist: refusing official wildcard cleanup')
    with c.cursor() as cur:
        cur.execute('SELECT coalesce(max(product_id),0) FROM public.products')
        high=cur.fetchone()[0]
        for table in ('order_items','inventory_log'):
            cur.execute(sql.SQL('SELECT count(*) FROM public.{} WHERE product_id BETWEEN %s AND %s').format(sql.Identifier(table)),(high+1000,high+1300))
            if cur.fetchone()[0]:
                raise RuntimeError('Official fixture range has historical references')
    return result

def hashes(c):
    result={}
    with c.cursor() as cur:
        for table,key in KEYS.items():
            cur.execute(sql.SQL("SELECT count(*),md5(string_agg(md5(to_jsonb(t)::text),'' ORDER BY {})) FROM public.{} t").format(sql.Identifier(key),sql.Identifier(table)))
            result[table]=cur.fetchone()
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','apply','suite','verify'])
    parser.add_argument('label',nargs='?',default='baseline')
    parser.add_argument('sql_file',nargs='?')
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',args.label):
        raise RuntimeError('Unsafe label')
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='new':
        raise RuntimeError('Expected branch new')
    LOGS.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    c,dsn,origin=connect()
    try:
        if args.command=='init':
            if (LOGS/'baseline.json').exists():
                raise RuntimeError('Existing baseline will not be overwritten')
            backup=HERE/'backups'
            backup.mkdir(exist_ok=True)
            shutil.copy2(ROOT/'functions/phase2_place_order.sql',backup/'phase2_place_order_original.sql')
            with c.cursor() as cur:
                cur.execute("SELECT pg_get_functiondef('public.place_order(bigint,bigint,integer)'::regprocedure)")
                (backup/'deployed_place_order_original.sql').write_text(cur.fetchone()[0],encoding='utf-8')
            baseline={'created_at':stamp,'credential_origin':origin,'safety':safety(c),'historical_fingerprints':hashes(c),
                      'environment':queries(c,HERE/'inspect_environment.sql'),
                      'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                      'git_status_before':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True),
                      'file_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts}}
            write(LOGS/'baseline.json',baseline)
            print(json.dumps({'initialized':True,'credential_origin':origin,'backups':str(backup.relative_to(ROOT))}))
            return
        baseline=json.loads((LOGS/'baseline.json').read_text())
        expected_safety=baseline['safety']
        # Normalize psycopg tuples to JSON lists before comparing.
        before=json.loads(json.dumps(safety(c)))
        if before!=expected_safety:
            raise RuntimeError('Counts/orphans differ from baseline before operation')
        if sha(ROOT/'race_test.py')!=baseline['file_sha256']['race_test.py']:
            raise RuntimeError('Official test was modified')
        if args.command=='apply':
            path=ROOT/args.sql_file
            with c.cursor() as cur:
                cur.execute("SELECT pg_get_functiondef('public.place_order(bigint,bigint,integer)'::regprocedure)")
                rollback=cur.fetchone()[0]
            snapshot=HERE/'backups'/f'before_{args.label}_{stamp}.sql'
            snapshot.write_text(rollback,encoding='utf-8')
            c.autocommit=False
            try:
                with c.cursor() as cur:
                    cur.execute(path.read_text(encoding='utf-8-sig'))
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.autocommit=True
            write(LOGS/f'apply_{args.label}_{stamp}.json',{'sql_file':str(path.relative_to(ROOT)),'sha256':sha(path),'rollback_file':str(snapshot.relative_to(ROOT))})
            print(json.dumps({'applied':args.label,'rollback_file':str(snapshot.relative_to(ROOT))}))
        elif args.command=='suite':
            environment=os.environ.copy()
            environment['DATABASE_URL']=dsn
            environment['PYTHONIOENCODING']='utf-8'
            # No open diagnostic connection or monitoring query during a race run.
            c.close()
            records=[]
            for test in [1]+[2]*args.repeats+[3,4]:
                index=len(records)+1
                command=[sys.executable,str(ROOT/'race_test.py'),'--test',str(test),'--verbose']
                start=time.perf_counter()
                process=subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace')
                elapsed=time.perf_counter()-start
                output=process.stdout+process.stderr
                path=LOGS/f'{args.label}_{stamp}_{index:02d}_test{test}.log'
                path.write_text(output,encoding='utf-8')
                m=re.search(r'(\d+) sold, (\d+) refused, (\d+) errored, wall clock ([\d.]+)s',output)
                record={'test':test,'process_seconds':elapsed,'exit_code':process.returncode,'output_log':path.relative_to(ROOT).as_posix()}
                if m:
                    record.update(dict(zip(('successful','refused','errors','official_wall_seconds'),(int(m[1]),int(m[2]),int(m[3]),float(m[4])))))
                c,_,_=connect()
                after=json.loads(json.dumps(safety(c)))
                record['counts_and_orphans_restored']=after==expected_safety
                record['fixture_checks']=after
                c.close()
                records.append(record)
                write(LOGS/f'{args.label}_{stamp}_results.json',records)
                print(json.dumps(record),flush=True)
                if process.returncode or after!=expected_safety or 'PASSED' not in output:
                    raise RuntimeError('Official test or cleanup failed; stop candidate')
            times=[r['official_wall_seconds'] for r in records if r['test']==2]
            print(json.dumps({'label':args.label,'test2_times':times,'median':statistics.median(times),'all_below_10':all(t<=10 for t in times)}))
        elif args.command=='verify':
            current=json.loads(json.dumps(hashes(c)))
            current_safety=json.loads(json.dumps(safety(c)))
            out={'historical_fingerprints_equal':current==baseline['historical_fingerprints'],
                 'historical_fingerprints':current,'counts_and_orphans_equal':current_safety==expected_safety,
                 'safety':current_safety,'race_test_unchanged':sha(ROOT/'race_test.py')==baseline['file_sha256']['race_test.py']}
            write(LOGS/f'verify_{args.label}_{stamp}.json',out)
            print(json.dumps(out))
            if not all(out[k] for k in ('historical_fingerprints_equal','counts_and_orphans_equal','race_test_unchanged')):
                raise RuntimeError('Final verification failed')
    finally:
        c.close()

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'sqlstate':getattr(exc,'pgcode',None)}))
        raise SystemExit(1) from None
