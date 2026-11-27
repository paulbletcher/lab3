"""Connection-only transport control; no checkout or data changes.

400 new connections + barrier + SELECT 1 + close, alternating default libpq
negotiation and explicit plaintext LOCAL transport. Only allowed if server SSL
is already disabled, so this does not remove an existing TLS protection.
This diagnostic is not an official performance acceptance result.
"""
import json
import os
import statistics
import threading
import time
from datetime import datetime,timezone
import psycopg2
from psycopg2.extensions import make_dsn
from run_experiment import connect,LOGS,write

def main():
    c,dsn,_=connect()
    with c.cursor() as cur:
        cur.execute('SHOW ssl')
        assert cur.fetchone()[0]=='off'
    c.close()
    records=[]
    for mode in ('default','local_direct','local_direct','default'):
        target=dsn if mode=='default' else make_dsn(dsn,sslmode='disable',gssencmode='disable')
        outcomes=[{} for _ in range(400)]
        release={}
        barrier=threading.Barrier(400,action=lambda:release.update(at=time.perf_counter()))
        def worker(index):
            connection=None
            try:
                opening=time.perf_counter()
                connection=psycopg2.connect(target)
                connection.autocommit=True
                opened=time.perf_counter()
                barrier.wait(timeout=60)
                with connection.cursor() as cur:
                    cur.execute('SELECT 1')
                    assert cur.fetchone()[0]==1
                outcomes[index]={'connection_ms':(opened-opening)*1000,'ok':True}
            except Exception as exc:
                outcomes[index]={'error_type':type(exc).__name__,'sqlstate':getattr(exc,'pgcode',None)}
                barrier.abort()
            finally:
                if connection is not None:
                    connection.close()
        threads=[threading.Thread(target=worker,args=(i,)) for i in range(400)]
        start=time.perf_counter()
        for t in threads:t.start()
        for t in threads:t.join()
        end=time.perf_counter()
        row={'mode':mode,'wall_seconds':end-start,'before_barrier_seconds':release.get('at',end)-start,
             'after_barrier_seconds':end-release.get('at',end),'successes':sum(r.get('ok',False) for r in outcomes),
             'errors':sum('error_type' in r for r in outcomes),'connection_ms':[r['connection_ms'] for r in outcomes if 'connection_ms' in r]}
        records.append(row)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        write(LOGS/'transport_control_results.json',records)
        print(json.dumps({k:v for k,v in row.items() if k!='connection_ms'}),flush=True)
        assert row['successes']==400 and row['errors']==0

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'sqlstate':getattr(exc,'pgcode',None)}))
        raise SystemExit(1) from None
