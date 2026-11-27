"""Verify checkout row locks in an empty disposable PostgreSQL database.

Run: python tests/verify_checkout_locking.py
Uses Python's standard library and Docker's psql, with one backend connection
per PsqlSession. No host DSN, password, confidential CSV or third-party driver
is needed. schema.sql runs ONLY in the generated database; load.sql never runs.
"""

import queue
import subprocess
import threading
import time
import uuid


CONTAINER = 'kloudkart'
TEST_DB = 'kloudkart_lock_test_' + uuid.uuid4().hex
NULL = '__NULL__'


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def command(arguments, sql=None):
    try:
        result = subprocess.run(
            ['docker', 'exec', '-i', '-w', '/lab', CONTAINER, *arguments],
            input=sql, text=True, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise VerificationError('Docker/PostgreSQL command exceeded 30 seconds') from None
    require(result.returncode == 0, 'Docker/PostgreSQL command failed; server details withheld')
    return result.stdout.strip()


def one_shot(database, sql=None, file=None):
    args = ['psql', '-U', 'postgres', '-d', database, '-X', '-qAt',
            '-v', 'ON_ERROR_STOP=1']
    if file:
        args += ['-f', file]
    return command(args, sql)


class PsqlSession:
    """An independent persistent backend; markers bound each command's output."""

    def __init__(self):
        self.pending = None
        self.pid = None
        self.lines = queue.Queue()
        self.process = subprocess.Popen(
            ['docker', 'exec', '-i', '-w', '/lab', '-e',
             'PGOPTIONS=-c statement_timeout=15000 -c lock_timeout=12000 '
             '-c idle_in_transaction_session_timeout=25000',
             CONTAINER, 'psql', '-U', 'postgres', '-d', TEST_DB, '-X', '-qAt',
             '-v', 'ON_ERROR_STOP=1', '-P', f'null={NULL}'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.pid = int(self.run('SELECT pg_backend_pid();')[0])
            require(self.run('SHOW transaction_isolation;') == ['read committed'],
                    'A locking session is not READ COMMITTED')
        except Exception:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line.rstrip('\r\n'))
        self.lines.put(None)

    def start(self, sql):
        require(self.pending is None, 'Session already has an unfinished command')
        self.pending = 'END_' + uuid.uuid4().hex
        try:
            self.process.stdin.write(sql + '\n\\echo ' + self.pending + '\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise VerificationError('PostgreSQL session closed unexpectedly') from None

    def finish(self, timeout=18):
        deadline = time.monotonic() + timeout
        output = []
        while True:
            try:
                line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                raise VerificationError('Session command exceeded its bounded wait') from None
            require(line is not None, 'PostgreSQL session failed; server details withheld')
            if line == self.pending:
                self.pending = None
                return output
            output.append(line)
            require(time.monotonic() < deadline, 'Session output exceeded its bounded wait')

    def run(self, sql):
        self.start(sql)
        return self.finish()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('\nROLLBACK;\n\\q\n')
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                if self.pid:
                    # Terminate only this script's backend in its generated database.
                    one_shot('postgres', f"""
                        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                        WHERE pid = {self.pid} AND datname = '{TEST_DB}';
                    """)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe and not pipe.closed:
                pipe.close()


def response_sql(product_id, quantity=5):
    return f'SELECT success, order_id, message FROM place_order(1::bigint, {product_id}::bigint, {quantity});'


def wait_until_blocked(observer, holder, waiter, test_id):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        rows = observer.run(f"""
            SELECT wait_event_type, wait_event,
                   {holder.pid} = ANY(pg_blocking_pids(pid))
            FROM pg_stat_activity WHERE pid = {waiter.pid};
        """)
        if rows and rows[0].startswith('Lock|') and rows[0].endswith('|t'):
            require(waiter.lines.empty(), 'Checkout finished before the blocker released its lock')
            print(f'{test_id}: observed wait_event_type=Lock; '
                  f'wait_event={rows[0].split("|")[1]}; '
                  'pg_blocking_pids includes holder; checkout unfinished', flush=True)
            return
        time.sleep(0.05)  # Poll actual server state; elapsed time is not proof of blocking.
    raise VerificationError(f'{test_id}: no monitored blocking relationship within six seconds')


def business_state(observer):
    return observer.run("""
        SELECT json_build_array(
          (SELECT COALESCE(json_agg(o ORDER BY order_id)::text, '[]') FROM orders o),
          (SELECT COALESCE(json_agg(i ORDER BY order_item_id)::text, '[]') FROM order_items i),
          (SELECT COALESCE(json_agg(l ORDER BY log_id)::text, '[]') FROM inventory_log l));
    """)


def check_case(observer, number):
    test_id = f'LOCK-{number:02d}'
    observer.run('UPDATE products SET price = 12.50, stock_quantity = 10;')
    original = business_state(observer)
    holder = PsqlSession()
    worker = None
    try:
        worker = PsqlSession()
        holder.run('BEGIN; SELECT product_id FROM products WHERE product_id = 1 FOR UPDATE;')
        product_id = 2 if number == 4 else 1
        quantity = 11 if number in (1, 4) else 5
        worker.start('BEGIN; ' + response_sql(product_id, quantity))
        expected_stock, expected_price = 10, 12.50
        if number == 4:
            result = worker.finish(timeout=5)
            require(holder.run('SELECT 1;') == ['1'], 'Holder transaction was lost')
            require(observer.run(f'SELECT cardinality(pg_blocking_pids({worker.pid}));') == ['0'],
                    'Different-product checkout was blocked')
            print('LOCK-04: different-product checkout completed while holder retained '
                  'its product-1 lock; worker blockers=0', flush=True)
        else:
            wait_until_blocked(observer, holder, worker, test_id)
            if number == 2:
                holder.run('UPDATE products SET stock_quantity = 2 WHERE product_id = 1; COMMIT;')
                expected_stock = 2
            elif number == 3:
                holder.run('UPDATE products SET price = 0 WHERE product_id = 1; COMMIT;')
                expected_price = 0
            else:
                holder.run('ROLLBACK;')
            result = worker.finish()

        expected_message = 'Invalid product price' if number == 3 else 'Product out of stock'
        require(result == [f'f|{NULL}|{expected_message}'],
                f'{test_id}: expected exactly one false/NULL refusal row')
        # The observer sees only the holder's intentional commits, never checkout writes.
        worker.run('COMMIT;')
        require(business_state(observer) == original, f'{test_id}: checkout changed business tables')
        product_rows = observer.run('SELECT product_id, price, stock_quantity FROM products ORDER BY product_id;')
        require(product_rows == [f'1|{expected_price:.2f}|{expected_stock}', '2|12.50|10'],
                f'{test_id}: checkout changed product values')
        print(f'{test_id}: PASS; rows=1, success=false, order_id=NULL, message={expected_message}; '
              'checkout business writes=0', flush=True)
    finally:
        # Release the blocker first so the waiter can finish even on a failed assertion.
        try:
            holder.close()
        finally:
            if worker:
                worker.close()


def main():
    observer = None
    created = False
    try:
        command(['createdb', '-U', 'postgres', '--template=template0', TEST_DB])
        created = True
        one_shot(TEST_DB, file='schema.sql')
        one_shot(TEST_DB, file='place_order.sql')
        one_shot(TEST_DB, """
            INSERT INTO customers (customer_id, full_name) VALUES (1, 'Synthetic lock test customer');
            INSERT INTO products (product_id, product_name, price, stock_quantity) VALUES
                (1, 'Synthetic lock product 1', 12.50, 10),
                (2, 'Synthetic lock product 2', 12.50, 10);
        """)
        observer = PsqlSession()
        print('Isolation: READ COMMITTED verified for observer and every holder/checkout session; '
              'no isolation changes', flush=True)
        print('Fixtures: disposable empty database; synthetic data only; no CSV loading', flush=True)
        for number in range(1, 5):
            check_case(observer, number)
        print('All four locking tests: PASS', flush=True)
    finally:
        try:
            if observer:
                observer.close()
        finally:
            if created:
                one_shot('postgres', f'DROP DATABASE "{TEST_DB}" WITH (FORCE);')
                remaining = one_shot('postgres',
                                     f"SELECT count(*) FROM pg_database WHERE datname = '{TEST_DB}';")
                require(remaining == '0', 'Disposable database cleanup failed')
                print('Cleanup (fresh connection): disposable database absent; PASS', flush=True)


if __name__ == '__main__':
    try:
        main()
    except VerificationError as error:
        print(f'FAIL: {error}', flush=True)
        raise SystemExit(1)
    except Exception:
        print('FAIL: unexpected verification error; details withheld to protect source values', flush=True)
        raise SystemExit(1)
