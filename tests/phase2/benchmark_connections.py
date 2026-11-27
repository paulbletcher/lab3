import os
import time
import threading
import statistics
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

BUYERS = 400
DSN = os.environ["DATABASE_URL"]

# Protect the original database.
uri = urlparse(DSN)

if uri.hostname != "127.0.0.1" or uri.port != 5433:
    raise RuntimeError("Expected the rebuilt database on port 5433.")

SQL = Path(__file__).with_name("connection_probe.sql").read_text()

connection_times = []
query_times = []
errors = []
release_time = None


def record_release():
    global release_time
    release_time = time.perf_counter()


barrier = threading.Barrier(BUYERS, action=record_release)


def worker():
    conn = None

    try:
        start = time.perf_counter()
        conn = psycopg2.connect(DSN, connect_timeout=30)
        conn.autocommit = True

        connection_times.append(
            time.perf_counter() - start
        )

        with conn.cursor() as cur:
            barrier.wait(timeout=60)

            start = time.perf_counter()
            cur.execute(SQL)
            cur.fetchone()

            query_times.append(
                time.perf_counter() - start
            )

    except Exception as exc:
        errors.append(type(exc).__name__)
        barrier.abort()

    finally:
        if conn is not None:
            conn.close()


start = time.perf_counter()

threads = [
    threading.Thread(target=worker)
    for _ in range(BUYERS)
]

for thread in threads:
    thread.start()

for thread in threads:
    thread.join()

end = time.perf_counter()

print("Connection Overhead Benchmark")
print("=" * 50)
print(f"Attempted connections: {BUYERS}")
print(f"Successful connections: {len(connection_times)}")
print(f"Successful queries: {len(query_times)}")
print(f"Errors: {len(errors)}")
print(f"Total wall-clock time: {end - start:.2f}s")

if release_time is not None:
    print(f"Time before barrier release: {release_time - start:.2f}s")
    print(f"Time after barrier release: {end - release_time:.2f}s")

if connection_times:
    print(f"Average connection time: {statistics.mean(connection_times):.4f}s")
    print(f"Maximum connection time: {max(connection_times):.4f}s")

if query_times:
    print(f"Average query time: {statistics.mean(query_times):.4f}s")
    print(f"Maximum query time: {max(query_times):.4f}s")

if errors:
    print(f"Error types: {set(errors)}")
    raise SystemExit(1)