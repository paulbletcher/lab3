"""Diagnostic connection-only control. Not an official acceptance test."""
import json
import os
import statistics
import threading
import time
import psycopg2

rows=[{} for _ in range(400)]
release={}
barrier=threading.Barrier(400,action=lambda:release.update(at=time.perf_counter()))


def worker(index):
    conn=None
    try:
        opening=time.perf_counter()
        conn=psycopg2.connect(os.environ['DATABASE_URL']);conn.autocommit=True
        opened=time.perf_counter();barrier.wait(timeout=60)
        started=time.perf_counter()
        with conn.cursor() as cur:
            cur.execute('SELECT 1');assert cur.fetchone()[0]==1
        rows[index]=dict(connection_ms=(opened-opening)*1000,query_ms=(time.perf_counter()-started)*1000)
    except Exception as exc:
        rows[index]=dict(error_type=type(exc).__name__);barrier.abort()
    finally:
        if conn is not None:conn.close()


threads=[threading.Thread(target=worker,args=(i,)) for i in range(400)]
started=time.perf_counter()
for t in threads:t.start()
for t in threads:t.join()
ended=time.perf_counter()
assert all(rows) and all('error_type' not in r for r in rows)
print(json.dumps(dict(total_seconds=ended-started,before_barrier_seconds=release['at']-started,
    after_barrier_seconds=ended-release['at'],successes=400,errors=0,
    connection_median_ms=statistics.median(r['connection_ms'] for r in rows),
    query_max_ms=max(r['query_ms'] for r in rows))))
