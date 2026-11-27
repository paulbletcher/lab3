"""Reproduce the submission on an isolated fresh database in kloudkart_rebuild.

python tests/final_verification.py --fresh
python tests/final_verification.py
--fresh creates a new database, refusing to overwrite any existing one.
No existing database is reset. Logs contain aggregate/synthetic evidence only.
Dependencies: Python 3, psycopg2-binary, Docker Desktop running PostgreSQL 18.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
import psycopg2
from psycopg2 import extensions, sql
from race_client import prepare_linux_client,run_race,verify_linux_authentication

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests'
CONTAINER = 'kloudkart_rebuild'
KEYS = dict(categories='category_id', products='product_id', customers='customer_id',
            orders='order_id', order_items='order_item_id', inventory_log='log_id')
COUNTS = dict(categories=94, products=4023, customers=40420, orders=159384,
              order_items=336559, inventory_log=282352)


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding='utf-8', errors='replace', **kwargs)


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def fingerprints(conn):
    result = {}
    with conn.cursor() as cur:
        for table, key in KEYS.items():
            cur.execute(sql.SQL("SELECT COUNT(*), md5(string_agg(md5(to_jsonb(t)::text),'' ORDER BY {})) FROM public.{} t")
                        .format(sql.Identifier(key), sql.Identifier(table)))
            result[table] = list(cur.fetchone())
    return result


def psql(db, path, logfile):
    command = ['docker', 'exec', '-w', '/lab', CONTAINER, 'psql', '-X', '-U', 'postgres',
               '-d', db, '-v', 'ON_ERROR_STOP=1', '-f', path]
    p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (OUT / logfile).write_text(p.stdout + p.stderr, encoding='utf-8')
    if p.returncode:
        raise RuntimeError(f'{path} failed; inspect tests/{logfile}')
    print(f'PASS {path}', flush=True)


def checkout_edges(conn):
    """All fixtures roll back, including successful checkout and forced failures."""
    checks = []
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT MIN(customer_id),MAX(customer_id)::bigint+1 FROM public.customers')
            customer, missing = cur.fetchone()
            pid = -850000000
            cur.execute("INSERT INTO public.products(product_id,product_name,price,stock_quantity) VALUES (%s,'SYNTHETIC CHECKOUT',100,10)", (pid,))

            def call(c, p, q):
                cur.execute('SELECT * FROM public.place_order(%s,%s,%s)', (c, p, q))
                return cur.fetchone()

            def refuse(label, c, p, q, message):
                cur.execute('SELECT (SELECT COUNT(*) FROM orders),(SELECT COUNT(*) FROM order_items),(SELECT COUNT(*) FROM inventory_log)')
                before = cur.fetchone()
                row = call(c, p, q)
                assert row[0] is False and row[1] is None and message in row[2].lower(), label
                cur.execute('SELECT (SELECT COUNT(*) FROM orders),(SELECT COUNT(*) FROM order_items),(SELECT COUNT(*) FROM inventory_log)')
                assert before == cur.fetchone(), label + ' partial writes'
                checks.append(label)

            for label, c, p, q, message in [
                ('null customer', None, pid, 1, 'invalid'),
                ('null product', customer, None, 1, 'invalid'),
                ('null quantity', customer, pid, None, 'invalid'),
                ('zero quantity', customer, pid, 0, 'invalid'),
                ('negative quantity', customer, pid, -1, 'invalid'),
                ('missing customer', missing, pid, 1, 'customer not found'),
                ('bigint customer', 2**40, pid, 1, 'customer not found'),
                ('bigint customer and product precedence', 2**40, 2**40, 1, 'customer not found'),
                ('missing product', customer, pid-1, 1, 'product not found'),
                ('bigint product', customer, 2**40, 1, 'product not found'),
                ('customer precedence', missing, pid-1, 1, 'customer not found'),
                ('oversell', customer, pid, 11, 'out of stock')]:
                refuse(label, c, p, q, message)
            for price, label in [(None, 'null price'), (-1, 'negative price')]:
                cur.execute('UPDATE products SET price=%s WHERE product_id=%s', (price, pid))
                refuse(label, customer, pid, 1, 'invalid product price')
            for stock, label in [(None, 'null stock'), (-1, 'negative stock')]:
                cur.execute('UPDATE products SET price=100,stock_quantity=%s WHERE product_id=%s', (stock, pid))
                refuse(label, customer, pid, 1, 'out of stock')
            cur.execute('UPDATE products SET price=9999999999.99,stock_quantity=2 WHERE product_id=%s', (pid,))
            cur.execute('SELECT (SELECT COUNT(*) FROM orders),(SELECT COUNT(*) FROM order_items),(SELECT COUNT(*) FROM inventory_log)')
            counts = cur.fetchone()
            cur.execute('SAVEPOINT fail_insert')
            try:
                call(customer, pid, 2)
            except psycopg2.errors.NumericValueOutOfRange:
                cur.execute('ROLLBACK TO SAVEPOINT fail_insert')
            else:
                raise AssertionError('Expected numeric insertion failure')
            cur.execute('SELECT stock_quantity FROM products WHERE product_id=%s', (pid,))
            assert cur.fetchone()[0] == 2
            cur.execute('SELECT (SELECT COUNT(*) FROM orders),(SELECT COUNT(*) FROM order_items),(SELECT COUNT(*) FROM inventory_log)')
            assert counts == cur.fetchone()
            checks.append('failed order INSERT restores stock and all write counts')
            # Fail the LAST write, after stock/order/item work has executed.
            cur.execute('UPDATE products SET price=100 WHERE product_id=%s',(pid,))
            cur.execute(sql.SQL('ALTER TABLE public.inventory_log ADD CONSTRAINT flash_checkout_audit_failure CHECK (product_id <> {}) NOT VALID').format(sql.Literal(pid)))
            cur.execute('SAVEPOINT fail_checkout_audit')
            try:
                call(customer,pid,1)
            except psycopg2.errors.CheckViolation:
                cur.execute('ROLLBACK TO SAVEPOINT fail_checkout_audit')
            else:
                raise AssertionError('Expected checkout audit insertion failure')
            cur.execute('SELECT stock_quantity FROM products WHERE product_id=%s',(pid,))
            assert cur.fetchone()[0]==2
            cur.execute('SELECT (SELECT COUNT(*) FROM orders),(SELECT COUNT(*) FROM order_items),(SELECT COUNT(*) FROM inventory_log)')
            assert counts==cur.fetchone()
            cur.execute('ALTER TABLE public.inventory_log DROP CONSTRAINT flash_checkout_audit_failure')
            checks.append('failed final checkout audit INSERT restores stock, order and item')
            cur.execute('UPDATE products SET price=0 WHERE product_id=%s', (pid,))
            assert call(customer, pid, 1)[0] is True
            checks.append('zero-priced checkout succeeds atomically; caller rollback follows')
    finally:
        conn.rollback()
        conn.autocommit = True
    return checks


def benchmarks(conn):
    result = {}
    plans = []
    with conn.cursor() as cur:
        cur.execute((OUT / 'reference_customer_spending.sql').read_text(encoding='utf-8'))
        for label, view in [('original_reference', 'pg_temp.reference_customer_spending'),
                            ('integrated_customer', 'public.report_customer_spending'),
                            ('recursive_low_stock', 'public.report_low_stock_by_category')]:
            times = []
            for number in range(1, 4):
                cur.execute(f'EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT * FROM {view}')
                plan = '\n'.join(r[0] for r in cur.fetchall())
                elapsed = float(re.search(r'Execution Time: ([\d.]+) ms', plan)[1])
                times.append(elapsed)
                plans.append(f'{label} run {number}\n{plan}\n')
                print(f'{label} run {number}: {elapsed:.3f} ms', flush=True)
            result[label] = dict(runs_ms=times, median_ms=statistics.median(times),
                                 worst_ms=max(times), p95='insufficiently sampled (n=3)')
    (OUT / 'final_plans.txt').write_text('\n'.join(plans), encoding='utf-8')
    write('final_performance.json', result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--database', default='kloudkart_submission_20261127')
    ap.add_argument('--race-repeats', type=int, default=3, help='Total Test 2 observations, including full suite')
    ap.add_argument('--race-client',choices=['linux','windows'],default='linux',
                    help='Unmodified harness client; Linux Docker client avoids Windows startup/proxy overhead')
    ap.add_argument('--allow-slow-race',action='store_true',help='Diagnostic only: save evidence without enforcing the ten-second target')
    args = ap.parse_args()
    if args.race_repeats < 1:
        raise RuntimeError('At least one race measurement is required')
    client_metadata=prepare_linux_client(OUT/'final_client_build.log') if args.race_client=='linux' else dict(
        client='native-windows',versions=dict(python=sys.version.split()[0],psycopg2=psycopg2.__version__.split()[0]),
        network='Windows loopback 127.0.0.1:5433 published Docker port',connections=400,harness_modified=False,connection_pool=False)
    if not re.fullmatch(r'kloudkart_submission_[a-z0-9_]+', args.database):
        raise RuntimeError('Only explicitly named disposable submission databases are allowed')
    detail = json.loads(run(['docker', 'inspect', CONTAINER]).stdout)[0]
    if detail['Name'] != '/' + CONTAINER or not detail['State']['Running']:
        raise RuntimeError('Wrong container')
    if not any(p['HostIp'] == '127.0.0.1' and p['HostPort'] == '5433'
               for p in detail['NetworkSettings']['Ports']['5432/tcp']):
        raise RuntimeError('Expected loopback port 5433')
    # Password stays in process memory/child environment. Never write the DSN.
    env = dict(x.split('=', 1) for x in detail['Config']['Env'] if '=' in x)
    base = dict(host='127.0.0.1', port=5433, user='postgres', password=env['POSTGRES_PASSWORD'])
    admin = psycopg2.connect(dbname='postgres', **base)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute('SELECT system_identifier::text FROM pg_control_system()')
        cluster = cur.fetchone()[0]
        expected = run(['docker', 'exec', CONTAINER, 'psql', '-X', '-U', 'postgres', '-d', 'postgres',
                        '-qAtc', 'SELECT system_identifier::text FROM pg_control_system()']).stdout.strip()
        if cluster != expected:
            raise RuntimeError('Host connection does not match named container')
        cur.execute("SELECT current_date,version(),current_setting('max_connections'),current_setting('work_mem'),current_setting('shared_buffers'),current_setting('TimeZone')")
        environment = [str(x) for x in cur.fetchone()]
        if args.fresh:
            cur.execute('SELECT EXISTS(SELECT FROM pg_database WHERE datname=%s)', (args.database,))
            if cur.fetchone()[0]:
                raise RuntimeError('Fresh load refuses an existing database; choose a new --database name')
    protected_before = fingerprints(admin)
    protected_files = [ROOT / x for x in ('schema.sql', 'load.sql', 'race_test.py')]
    protected_files += sorted((ROOT / 'data').glob('*.csv'))
    hashes_before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_files}
    head_before = run(['git','rev-parse','HEAD']).stdout.strip()
    if run(['git','branch','--show-current']).stdout.strip() != 'new':
        raise RuntimeError('Expected branch new')
    if args.fresh:
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(args.database)))
        psql(args.database, 'schema.sql', 'final_schema.log')
        psql(args.database, 'load.sql', 'final_load.log')
    conn = psycopg2.connect(dbname=args.database, **base)
    conn.autocommit = True
    before = fingerprints(conn)
    assert {k:v[0] for k,v in before.items()} == COUNTS, 'Fresh baseline counts differ'
    print('PASS all six fresh-load row counts', flush=True)
    psql(args.database, 'run_all.sql', 'final_install.log')
    # Reinstallation is checked without resetting consumed sequence values.
    with conn.cursor() as cur:
        cur.execute("SELECT nextval('orders_order_id_seq')")
        consumed = cur.fetchone()[0]
    psql(args.database, 'run_all.sql', 'final_reinstall.log')
    with conn.cursor() as cur:
        cur.execute("SELECT nextval('orders_order_id_seq')")
        assert cur.fetchone()[0] > consumed, 'Reinstall rewound a sequence'
    for source, log in [
        ('tests/phase2/test_place_order.sql', 'final_checkout.log'),
        ('tests/inventory_audit/04_test_inventory_movement.sql', 'final_movements.log'),
        ('tests/inventory_audit/05_test_inventory_rollback.sql', 'final_audit_rollback.log'),
        ('tests/inventory_audit/07_test_inventory_permissions.sql', 'final_permissions.log'),
        ('tests/final_reporting.sql', 'final_reporting.log'),
        ('tests/final_recursive.sql', 'final_recursive.log'),
        ('tests/final_improvement.sql', 'final_improvement.log')]:
        psql(args.database, source, log)
    edge_checks = checkout_edges(conn)
    assert fingerprints(conn) == before, 'Synthetic SQL/edge fixtures survived rollback'
    with conn.cursor() as cur:
        cur.execute("SELECT exception_type,COUNT(*),SUM(stored_amount),SUM(difference) FROM report_order_review_queue GROUP BY exception_type ORDER BY exception_type")
        queue_counts = cur.fetchall()
        cur.execute('SELECT COUNT(DISTINCT order_id),COUNT(*) FROM report_order_review_queue')
        queue_unique = cur.fetchone()
        cur.execute("SELECT COUNT(*) FILTER (WHERE created_at IS NULL),COUNT(*) FILTER (WHERE created_at>=CURRENT_DATE+INTERVAL '1 day'), COUNT(*) FILTER (WHERE reason='sale' AND change_qty<0 AND created_at>=CURRENT_DATE-INTERVAL '30 days' AND created_at<CURRENT_DATE), MAX(created_at) FILTER (WHERE created_at<CURRENT_DATE+INTERVAL '1 day') FROM inventory_log")
        inventory_profile = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM products WHERE product_name LIKE 'RACE TEST FIXTURE%'")
        assert cur.fetchone()[0] == 0, 'Existing official fixtures; refusing cleanup'
        cur.execute('SELECT COALESCE(MAX(product_id),0)+1000 FROM products')
        pid = cur.fetchone()[0]
        for table in ('order_items','inventory_log'):
            cur.execute(sql.SQL('SELECT COUNT(*) FROM {} WHERE product_id BETWEEN %s AND %s').format(sql.Identifier(table)), (pid,pid+300))
            assert cur.fetchone()[0] == 0, 'Official fixture range overlaps historical references'
    # Close diagnostic connections while timing the exact supplied harness.
    conn.close()
    admin.close()
    dsn=extensions.make_dsn(dbname=args.database, **base)
    if args.race_client=='linux':
        auth=verify_linux_authentication(dsn)
        assert auth['database']==args.database and auth['cluster']==cluster
        client_metadata['authentication_preflight']=auth
        client_metadata['authentication']='scram-sha-256 on bridge address; invalid password rejected'
    start = time.perf_counter()
    race = run_race(dsn,['--verbose'],client=args.race_client)
    (OUT/'final_race.log').write_text(race.stdout+race.stderr,encoding='utf-8')
    if race.returncode or 'PASSED' not in race.stdout:
        raise RuntimeError('Official harness failed; inspect tests/final_race.log')
    race_seconds = time.perf_counter() - start
    m = re.search(r'(\d+) sold, (\d+) refused, (\d+) errored, wall clock ([\d.]+)s',race.stdout)
    race_result = dict(successes=int(m[1]),refusals=int(m[2]),errors=int(m[3]),
                       flash_seconds=float(m[4]),process_seconds=race_seconds,all_four_passed=True)
    assert (race_result['successes'],race_result['refusals'],race_result['errors']) == (50,350,0)
    trail = race.stdout.split('Test 4')[-1]
    trail_counts = re.search(r'(\d+) sold, (\d+) movements recorded', trail)
    assert trail_counts and (int(trail_counts[1]),int(trail_counts[2])) == (5,5), 'Exact test 4 audit counts'
    assert trail.count('success=False') == 7 and trail.count('success=True') == 5
    race_result['audit_test'] = dict(successes=5,refusals=7,movements=5)
    assert '25/25 rounds: exactly one winner' in race.stdout
    race_result['last_unit_test'] = dict(rounds=25,successes=25,refusals=25)
    race_result['flash_runs_seconds'] = [race_result['flash_seconds']]
    print('PASS official four-test harness: '+json.dumps(race_result),flush=True)
    for number in range(2,args.race_repeats+1):
        extra = run_race(dsn,['--test','2','--verbose'],client=args.race_client)
        (OUT/f'final_race_repeat_{number}.log').write_text(extra.stdout+extra.stderr,encoding='utf-8')
        match = re.search(r'(\d+) sold, (\d+) refused, (\d+) errored, wall clock ([\d.]+)s',extra.stdout)
        assert extra.returncode == 0 and 'PASSED' in extra.stdout and match, 'Repeated official test 2 failed'
        assert tuple(int(match[i]) for i in (1,2,3)) == (50,350,0)
        race_result['flash_runs_seconds'].append(float(match[4]))
        print(f'PASS repeated official Test 2 run {number}: {match[4]} s',flush=True)
    race_result['flash_median_seconds'] = statistics.median(race_result['flash_runs_seconds'])
    race_result['flash_worst_seconds'] = max(race_result['flash_runs_seconds'])
    race_result['flash_target_all_runs_met'] = race_result['flash_worst_seconds'] <= 10
    conn = psycopg2.connect(dbname=args.database, **base)
    conn.autocommit = True
    assert fingerprints(conn) == before, 'Harness did not restore all six tables'
    perf = benchmarks(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT tablename,indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2")
        indexes = cur.fetchall()
        assert len(indexes) == 6, 'Unexpected additional index'
        cur.execute("SELECT COUNT(*) FROM pg_trigger WHERE NOT tgisinternal")
        assert cur.fetchone()[0] == 0, 'Unexpected custom trigger'
        cur.execute("SELECT prosrc FROM pg_proc WHERE oid='public.place_order(bigint,bigint,integer)'::regprocedure")
        body = cur.fetchone()[0]
        assert body.replace('\r\n','\n').strip() == (ROOT/'functions/phase3_place_order.sql').read_text(encoding='utf-8').split('$$')[1].strip(), 'Deployed checkout source differs beyond line endings'
    conn.close()
    admin = psycopg2.connect(dbname='postgres', **base)
    admin.autocommit = True
    assert fingerprints(admin) == protected_before, 'Existing rebuilt database data changed'
    admin.close()
    assert hashes_before == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_files}
    assert head_before == run(['git','rev-parse','HEAD']).stdout.strip()
    info = json.loads(run(['docker','info','--format','{{json .}}']).stdout)
    spec = {k:info.get(k) for k in ('NCPU','MemTotal','OSType','Architecture','KernelVersion','ServerVersion')}
    evidence = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),database=args.database,
        container=CONTAINER,environment=environment,docker_resources=spec,race_client=client_metadata,
        container_limits={k:detail['HostConfig'].get(k) for k in ('Memory','NanoCpus','CpuQuota','CpuPeriod')},
        six_table_fingerprints=before,protected_file_sha256=hashes_before,
        existing_rebuilt_data_unchanged=True,source_files_unchanged=True,git_head_unchanged=True,
        original_container_untouched=True,reinstallation_preserves_sequence_progress=True,
        sql_test_logs=['final_checkout.log','final_movements.log','final_audit_rollback.log','final_permissions.log',
                       'final_reporting.log','final_recursive.log','final_improvement.log'],
        checkout_edge_checks=edge_checks,review_queue_groups=queue_counts,review_queue_unique_and_flags=queue_unique,
        inventory_profile=inventory_profile,race=race_result,performance=perf,indexes=indexes,
        all_checks_passed=True, all_checks_scope="correctness, installation and preservation; latency is reported separately",
        performance_targets=dict(flash_all_runs_within_ten_seconds=race_result['flash_target_all_runs_met']))
    write('final_evidence.json',evidence)
    print('PASS final fingerprints, source preservation, deployment and evidence',flush=True)
    if not race_result['flash_target_all_runs_met'] and not args.allow_slow_race:
        raise RuntimeError('Correctness passed, but flash-sale latency exceeded ten seconds; see final_evidence.json')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Avoid exception DSNs or customer rows in output. Logs identify SQL failures.
        print(f'FAILED: {type(exc).__name__}: {exc}' if isinstance(exc,(AssertionError,RuntimeError))
              else f'FAILED: {type(exc).__name__}; SQLSTATE={getattr(exc,"pgcode",None)}',flush=True)
        raise SystemExit(1) from None
