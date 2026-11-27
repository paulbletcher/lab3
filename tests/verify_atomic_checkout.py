"""Test atomic checkout, then run the unmodified official race harness.

Run from the project root: python tests/verify_atomic_checkout.py
Requires Docker and psycopg2. Uses a disposable PostgreSQL 18 container with
500 connections, synthetic data only and a port bound exclusively to loopback.
The active kloudkart container and confidential CSV files are never accessed.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = uuid.uuid4().hex[:12]
CONTAINER = 'kloudkart_atomic_' + RUN_ID
RESULTS = ROOT / 'tests' / 'results'
DSN = None


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def docker(*args, check=True, timeout=30):
    result = subprocess.run(['docker', *args], capture_output=True, text=True,
                            encoding='utf-8', timeout=timeout)
    if check:
        require(result.returncode == 0, 'Docker command failed; captured details withheld')
    return result


def query(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


@contextmanager
def session(autocommit=False):
    conn = psycopg2.connect(DSN, connect_timeout=15,
                           options='-c statement_timeout=30000 -c lock_timeout=15000 '
                                   '-c idle_in_transaction_session_timeout=60000')
    try:
        conn.autocommit = autocommit
        require(query(conn, 'SHOW transaction_isolation') == [('read committed',)],
                'Test connection is not READ COMMITTED')
        yield conn
    finally:
        if not conn.closed:
            if not autocommit:
                conn.rollback()
            conn.close()


def fixture(conn, product_id, stock, price=Decimal('12.50')):
    query(conn, '''INSERT INTO products (product_id, product_name, price, stock_quantity)
                  VALUES (%s, %s, %s, %s)''',
          (product_id, 'ATOMIC SYNTHETIC ' + str(product_id), price, stock))


def call(conn, product_id, quantity, customer_id=1):
    return query(conn, 'SELECT success, order_id, message FROM place_order(%s::bigint,%s::bigint,%s)',
                 (customer_id, product_id, quantity))


def state(conn):
    # These tables contain synthetic data only. Compare full rows, not just counts.
    return tuple(query(conn, 'SELECT * FROM ' + table + ' ORDER BY 1')
                 for table in ('products', 'orders', 'order_items', 'inventory_log'))


def check_success(number, stock, quantity):
    with session() as conn:
        fixture(conn, 100 + number, stock)
        rows = call(conn, 100 + number, quantity)
        require(len(rows) == 1 and rows[0][0] is True and isinstance(rows[0][1], int)
                and rows[0][1] > 0 and rows[0][2] == 'Order placed successfully',
                f'ORDER-{number:02d}: invalid success response')
        order_id = rows[0][1]
        require(query(conn, '''SELECT customer_id, status, total_amount,
                                      order_date = transaction_timestamp()::timestamp
                               FROM orders WHERE order_id = %s''', (order_id,)) ==
                [(1, 'pending', Decimal('12.50') * quantity, True)],
                'Wrong order values or database timestamp')
        items = query(conn, '''SELECT order_item_id, order_id, product_id, quantity, unit_price
                               FROM order_items''')
        require(len(items) == 1 and items[0][0] > 0 and items[0][1:] ==
                (order_id, 100 + number, quantity, Decimal('12.50')), 'Wrong order item')
        logs = query(conn, '''SELECT log_id, product_id, change_qty, reason, note,
                                    created_at = transaction_timestamp()::timestamp
                             FROM inventory_log''')
        require(len(logs) == 1 and logs[0][0] > 0 and logs[0][1:] ==
                (100 + number, -quantity, 'sale', f'Order {order_id}', True),
                'Wrong inventory movement, note or timestamp')
        require(query(conn, 'SELECT stock_quantity FROM products WHERE product_id=%s',
                      (100 + number,)) == [(stock - quantity,)], 'Wrong stock deduction')
        require(query(conn, 'SELECT count(*) FROM orders') == [(1,)], 'Wrong order count')
        print(f'ORDER-{number:02d}: PASS; quantity={quantity}, stock={stock}->{stock - quantity}, '
              f'pending total={Decimal("12.50") * quantity}; generated order/item/log IDs; '
              'one matching sale movement and database timestamps', flush=True)


def check_refusals():
    cases = [
        ('REFUSE-01', 2, Decimal('12.50'), 3, 1, 201, 'Product out of stock'),
        ('REFUSE-02', 0, Decimal('12.50'), 1, 1, 201, 'Product out of stock'),
        ('REFUSE-03', -1, Decimal('12.50'), 1, 1, 201, 'Invalid stock quantity'),
        ('REFUSE-04', None, Decimal('12.50'), 1, 1, 201, 'Stock quantity unavailable'),
        ('REFUSE-05', 10, Decimal('0'), 1, 1, 201, 'Invalid product price'),
        ('REFUSE-06', 10, Decimal('12.50'), 1, 2147483648, 201, 'Customer not found'),
        ('REFUSE-07', 10, Decimal('12.50'), 1, 1, 2147483648, 'Product not found'),
    ]
    for test_id, stock, price, quantity, customer, product, message in cases:
        with session() as conn:
            fixture(conn, 201, stock, price)
            before = state(conn)
            require(call(conn, product, quantity, customer) == [(False, None, message)],
                    test_id + ': refusal response mismatch')
            require(state(conn) == before, test_id + ': refusal changed business rows')
            print(f'{test_id}: PASS; one false/NULL row, {message}; '
                  'stock and all business rows unchanged', flush=True)


def check_rollback():
    with session() as conn:
        fixture(conn, 301, 5)
        query(conn, '''
            CREATE FUNCTION pg_temp.atomic_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM order_items i JOIN orders o USING (order_id)
                    JOIN products p ON p.product_id=i.product_id
                    WHERE p.product_id=301 AND p.stock_quantity=3 AND i.quantity=2
                      AND o.status='pending' AND NEW.note='Order ' || o.order_id::text
                ) THEN
                    RAISE EXCEPTION 'Injection did not observe earlier checkout writes'
                        USING ERRCODE='P0002';
                END IF;
                RAISE EXCEPTION 'Controlled inventory insertion failure' USING ERRCODE='P0001';
            END $$;
            CREATE TRIGGER atomic_test_failure BEFORE INSERT ON inventory_log
                FOR EACH ROW EXECUTE FUNCTION pg_temp.atomic_test_failure();
        ''')
        before = state(conn)
        query(conn, 'SAVEPOINT before_checkout')
        caught = False
        try:
            call(conn, 301, 2)
        except psycopg2.Error as error:
            caught = error.pgcode == 'P0001' and error.diag.message_primary == \
                'Controlled inventory insertion failure'
            query(conn, 'ROLLBACK TO SAVEPOINT before_checkout')
        require(caught, 'ROLLBACK-01: expected controlled inventory failure did not propagate')
        require(state(conn) == before, 'ROLLBACK-01: partial checkout writes remained')
        print('ROLLBACK-01: PASS; test trigger observed stock=3, pending order and item, '
              'then raised P0001; stock restored to 5; orders/items/movements=0', flush=True)
    with session(autocommit=True) as fresh:
        require(query(fresh, '''SELECT count(*) FROM pg_trigger
                               WHERE NOT tgisinternal AND tgname='atomic_test_failure' ''') == [(0,)],
                'Test trigger remained after rollback')
        require(query(fresh, '''SELECT count(*) FROM pg_proc
                               WHERE proname='atomic_test_failure' ''') == [(0,)],
                'Test trigger function remained after rollback')
        print('ROLLBACK-01 cleanup: fresh connection found zero test triggers/functions', flush=True)


def wait_blocked(observer, holder_pid, waiter_pid, label):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        rows = query(observer, '''SELECT wait_event_type, wait_event,
                                        %s = ANY(pg_blocking_pids(pid))
                                 FROM pg_stat_activity WHERE pid=%s''', (holder_pid, waiter_pid))
        if rows and rows[0][0] == 'Lock' and rows[0][2] is True:
            print(f'{label}: monitored Lock/{rows[0][1]}; '
                  'pg_blocking_pids includes checkout holder', flush=True)
            return
        time.sleep(0.05)
    raise VerificationError(label + ': expected blocking relationship not observed')


def check_customer_lock(number):
    label = f'CUSTOMER-LOCK-{number:02d}'
    with session(autocommit=True) as setup:
        fixture(setup, 400 + number, 5)
    try:
        with session() as checkout, session() as modifier, session(autocommit=True) as observer:
            result = call(checkout, 400 + number, 1)
            require(len(result) == 1 and result[0][0] is True, label + ': checkout failed')
            holder_pid = checkout.get_backend_pid()
            waiter_pid = modifier.get_backend_pid()
            sql = ('DELETE FROM customers WHERE customer_id=1 RETURNING customer_id' if number == 1
                   else 'UPDATE customers SET customer_id=2 WHERE customer_id=1 RETURNING customer_id')
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(query, modifier, sql)
                try:
                    wait_blocked(observer, holder_pid, waiter_pid, label)
                    require(not pending.done(), label + ': key modification completed too early')
                finally:
                    checkout.rollback()
                require(len(pending.result(timeout=10)) == 1, label + ': modifier did not resume')
                modifier.rollback()
            require(query(observer, 'SELECT customer_id FROM customers') == [(1,)],
                    label + ': customer fixture was changed')
            print(label + ': PASS; customer ' + ('deletion' if number == 1 else 'key update') +
                  ' waited until checkout transaction ended; both transactions rolled back', flush=True)
    finally:
        with session(autocommit=True) as cleanup:
            query(cleanup, 'DELETE FROM products WHERE product_id=%s', (400 + number,))


def check_concurrent_ids():
    buyers = 20
    with session(autocommit=True) as setup:
        fixture(setup, 501, buyers)
    barrier = threading.Barrier(buyers)

    def buy(_):
        with session(autocommit=True) as conn:
            barrier.wait(timeout=20)
            rows = call(conn, 501, 1)
            require(len(rows) == 1 and rows[0][0] is True, 'Concurrent purchase did not succeed')
            return rows[0][1]

    with ThreadPoolExecutor(max_workers=buyers) as pool:
        order_ids = list(pool.map(buy, range(buyers)))
    require(len(set(order_ids)) == buyers, 'Concurrent order IDs are not unique')
    with session(autocommit=True) as conn:
        counts = query(conn, '''SELECT
            (SELECT count(*) FROM orders), (SELECT count(DISTINCT order_id) FROM orders),
            (SELECT count(*) FROM order_items), (SELECT count(DISTINCT order_item_id) FROM order_items),
            (SELECT count(*) FROM inventory_log), (SELECT count(DISTINCT log_id) FROM inventory_log)''')
        require(counts == [(buyers,) * 6], 'Concurrent generated IDs or row counts are wrong')
        require(query(conn, '''SELECT count(*) FROM orders o JOIN order_items i USING (order_id)
            JOIN inventory_log l ON l.note='Order ' || o.order_id::text
            WHERE o.status='pending' AND o.total_amount=12.50 AND i.product_id=501
              AND i.quantity=1 AND i.unit_price=12.50 AND l.product_id=501
              AND l.change_qty=-1 AND l.reason='sale' ''') == [(buyers,)],
                'Concurrent purchases have inconsistent order/item/audit details')
        require(query(conn, 'SELECT stock_quantity FROM products WHERE product_id=501') == [(0,)],
                'Concurrent stock deduction is wrong')
        print('ID-01: PASS; 20 concurrent committed successes; 20 unique order IDs, '
              '20 unique item IDs, 20 unique log IDs; 20 exact sale links; stock=0', flush=True)
        query(conn, '''DELETE FROM inventory_log; DELETE FROM order_items;
                       DELETE FROM orders; DELETE FROM products WHERE product_id=501''')


def verify_clean(label):
    with session(autocommit=True) as conn:
        counts = query(conn, '''SELECT (SELECT count(*) FROM products),
            (SELECT count(*) FROM orders), (SELECT count(*) FROM order_items),
            (SELECT count(*) FROM inventory_log),
            (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal),
            (SELECT count(*) FROM pg_proc WHERE proname='atomic_test_failure')''')
        require(counts == [(0, 0, 0, 0, 0, 0)], label + ': fixtures or test objects remain')
        print(label + ': fresh connection; products/orders/items/logs/test triggers/functions=0; PASS',
              flush=True)


def timed(label, function, *args):
    started = time.perf_counter()
    function(*args)
    print(f'Timing {label}: {time.perf_counter() - started:.3f}s', flush=True)


def official_race(path):
    original_hash = hashlib.sha256((ROOT / 'race_test.py').read_bytes()).hexdigest()
    environment = dict(os.environ, DATABASE_URL=DSN, PYTHONIOENCODING='utf-8')
    started = time.perf_counter()
    try:
        result = subprocess.run([sys.executable, str(ROOT / 'race_test.py')], cwd=ROOT,
                                env=environment, capture_output=True, text=True,
                                encoding='utf-8', timeout=240)
    except subprocess.TimeoutExpired as error:
        with path.open('x', encoding='utf-8') as evidence:
            for captured in (error.stdout, error.stderr):
                if captured:
                    evidence.write(captured.decode('utf-8') if isinstance(captured, bytes) else captured)
            evidence.write('\nOfficial race exceeded 240 seconds; FAIL\n')
        raise VerificationError('Official race timed out; partial output preserved') from None
    elapsed = time.perf_counter() - started
    with path.open('x', encoding='utf-8') as evidence:
        evidence.write(result.stdout)
        evidence.write(result.stderr)
        evidence.write(f'\nActual process elapsed: {elapsed:.3f}s\nExit status: {result.returncode}\n')
    print(result.stdout, end='', flush=True)
    if result.stderr:
        print(result.stderr, end='', flush=True)
    print(f'Official race actual process elapsed: {elapsed:.3f}s; exit={result.returncode}', flush=True)
    require(hashlib.sha256((ROOT / 'race_test.py').read_bytes()).hexdigest() == original_hash,
            'Official race source changed')
    require(result.returncode == 0, 'Official race failed; actual output preserved')


def main():
    global DSN
    started = time.perf_counter()
    try:
        docker('run', '--detach', '--rm', '--name', CONTAINER,
               '--mount', f'type=bind,source={ROOT},target=/lab,readonly',
               '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-p', '127.0.0.1::5432',
               'postgres:18', '-c', 'max_connections=500')
        deadline = time.monotonic() + 40
        while True:
            ready = docker('exec', CONTAINER, 'pg_isready', '-h', '127.0.0.1',
                           '-U', 'postgres', check=False)
            if ready.returncode == 0:
                break
            require(time.monotonic() < deadline, 'Disposable PostgreSQL startup timed out')
            time.sleep(0.2)
        port = docker('port', CONTAINER, '5432/tcp').stdout.strip().rsplit(':', 1)[1]
        DSN = f'postgresql://postgres@127.0.0.1:{port}/postgres'
        for file in ('schema.sql', 'checkout.sql', 'place_order.sql'):
            docker('exec', '-w', '/lab', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
                   '-X', '-v', 'ON_ERROR_STOP=1', '-f', file)
        with session(autocommit=True) as conn:
            query(conn, "INSERT INTO customers (customer_id,full_name) VALUES (1,'ATOMIC SYNTHETIC CUSTOMER')")
            require(query(conn, '''SELECT count(*) FROM information_schema.columns
                WHERE table_schema='public' AND identity_generation='ALWAYS'
                AND (table_name,column_name) IN (('orders','order_id'),
                    ('order_items','order_item_id'),('inventory_log','log_id'))''') == [(3,)],
                    'Three generated ALWAYS identities are required')
            print('Environment: synthetic-only PostgreSQL 18; max_connections=' +
                  query(conn, 'SHOW max_connections')[0][0] +
                  '; every native test session verifies READ COMMITTED', flush=True)
            print('ID setup: existing checkout.sql applied after empty schema; all three ALWAYS identities verified',
                  flush=True)
        timed('one-unit purchase', check_success, 1, 5, 1)
        timed('multiple-unit purchase', check_success, 2, 10, 3)
        timed('exact-stock purchase', check_success, 3, 4, 4)
        timed('seven refusal/no-change cases', check_refusals)
        timed('controlled rollback', check_rollback)
        timed('customer deletion lock', check_customer_lock, 1)
        timed('customer key update lock', check_customer_lock, 2)
        timed('concurrent ID generation and exact audit links', check_concurrent_ids)
        verify_clean('Preliminary fixture cleanup')
        print('All preliminary assertions passed; running race_test.py unchanged with all four tests', flush=True)
        official_race(RESULTS / f'atomic_official_race_{RUN_ID}.txt')
        verify_clean('Official race fixture cleanup')
    finally:
        # This exact generated container owns its data volume; the project mount is read-only.
        removal = docker('rm', '--force', '--volumes', CONTAINER, check=False)
        remaining = docker('ps', '--all', '--quiet', '--filter', f'name=^/{CONTAINER}$')
        require(not remaining.stdout.strip(), 'Disposable container cleanup failed')
        print('Cleanup: disposable container absent; its anonymous data volume removed; active kloudkart untouched',
              flush=True)
        print(f'Total verification elapsed: {time.perf_counter() - started:.3f}s', flush=True)


class Tee:
    def __init__(self, console, evidence):
        self.console, self.evidence = console, evidence

    def write(self, value):
        self.console.write(value)
        self.evidence.write(value)
        self.evidence.flush()

    def flush(self):
        self.console.flush()
        self.evidence.flush()


if __name__ == '__main__':
    RESULTS.mkdir(exist_ok=True)
    evidence_path = RESULTS / f'atomic_order_verification_{RUN_ID}.txt'
    with evidence_path.open('x', encoding='utf-8') as evidence:
        original_stdout = sys.stdout
        sys.stdout = Tee(original_stdout, evidence)
        try:
            main()
        except Exception as error:
            if isinstance(error, VerificationError):
                print('FAIL: ' + str(error), flush=True)
            else:
                print(f'FAIL: {type(error).__name__}; SQLSTATE={getattr(error, "pgcode", None)}; '
                      'details withheld', flush=True)
            raise SystemExit(1)
        finally:
            sys.stdout = original_stdout
    print('Verification evidence: ' + str(evidence_path.relative_to(ROOT)), flush=True)
