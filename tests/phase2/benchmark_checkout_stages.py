"""Investigation 6: instrumented checkout, with the official autocommit boundary.

Run from the project root: python tests/phase2/benchmark_checkout_stages.py
Requires DATABASE_URL targeting 127.0.0.1:5433/postgres as postgres. Credentials
are never logged. The runner only deletes its own synthetic product and orders.
It creates a unique diagnostic schema and removes it without CASCADE afterwards.

An implicit commit has no separately timed psycopg2 commit() call. We therefore
report post-function-to-client-acknowledgement estimates, NOT commit durations.
Server/client clock mapping is calibrated before and after the workload, outside
the wall-clock timer; its uncertainty bounds are retained per buyer. These tails
also include result construction, protocol delivery and client scheduling.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg2
from psycopg2 import extensions, sql

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"
BUYERS, STOCK = 400, 50
TABLES = ("customers", "categories", "products", "orders", "order_items", "inventory_log")
FIELDS = (
    "stock_update_ms", "order_insert_ms", "order_item_insert_ms",
    "inventory_log_insert_ms", "function_ms", "post_update_function_ms",
)


def emit(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exception_tag(exc):
    # Never log exception text: driver messages can contain data or DSNs.
    return {"type": type(exc).__name__, "sqlstate": getattr(exc, "pgcode", None)}


def fingerprint(cur):
    cur.execute("""
        SELECT md5(pg_get_functiondef('public.place_order(bigint,bigint,integer)'::regprocedure)),
               (SELECT md5(coalesce(string_agg(indexdef, E'\n' ORDER BY indexname), ''))
                FROM pg_indexes WHERE schemaname = 'public'),
               (SELECT md5(coalesce(string_agg(pg_get_triggerdef(t.oid), E'\n' ORDER BY t.oid), ''))
                FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE NOT t.tgisinternal AND n.nspname = 'public')
    """)
    return dict(zip(("public_place_order", "public_indexes", "public_triggers"), cur.fetchone()))


def counts(cur):
    answer = {}
    for table in TABLES:
        cur.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table)))
        answer[table] = cur.fetchone()[0]
    return answer


def fixture_checks(cur):
    source = (HERE / "check_fixture_cleanup.sql").read_text(encoding="utf-8-sig")
    source = re.sub(r"--[^\n]*", "", source)
    results = []
    for statement in source.split(";"):
        if statement.strip():
            cur.execute(statement)
            columns = [entry.name for entry in cur.description]
            # The candidate fixture key is synthetic, but do not log any record IDs.
            results.append([{k: v for k, v in zip(columns, row) if k != "next_fixture_id"}
                            for row in cur.fetchall()])
    return results


def clock_calibration(cur):
    trials = []
    for _ in range(9):
        sent = time.perf_counter()
        cur.execute("SELECT extract(epoch FROM clock_timestamp())::double precision")
        epoch = cur.fetchone()[0]
        received = time.perf_counter()
        trials.append({"offset_low_s": epoch - received,
                       "offset_high_s": epoch - sent,
                       "rtt_ms": (received - sent) * 1000})
    # The shortest round trip gives the narrowest clock-offset bracket.
    return min(trials, key=lambda item: item["rtt_ms"])


def describe(values):
    values = [value for value in values if value is not None]
    if not values:
        return {"n": 0, "avg_ms": None, "median_ms": None, "max_ms": None}
    return {"n": len(values), "avg_ms": statistics.mean(values),
            "median_ms": statistics.median(values), "max_ms": max(values)}


def main():
    LOGS.mkdir(exist_ok=True)
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    results_path = LOGS / f"checkout_stages_{run}.jsonl"
    safety_path = LOGS / f"checkout_fixture_safety_{run}.jsonl"
    output_path = LOGS / f"checkout_benchmark_{run}.log"
    schema = "diagnostics_i6_" + uuid.uuid4().hex[:12]
    fixture_name = "RACE TEST FIXTURE I6 " + run
    source_paths = (ROOT / "race_test.py", ROOT / "functions/phase2_place_order.sql")
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
    if subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() != "new":
        raise RuntimeError("Expected branch new")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL must be supplied privately in the process environment")
    parsed = extensions.parse_dsn(dsn)
    if (parsed.get("host"), parsed.get("port"), parsed.get("dbname"), parsed.get("user")) != (
            "127.0.0.1", "5433", "postgres", "postgres"):
        raise RuntimeError("Refusing any endpoint except rebuilt localhost:5433/postgres as postgres")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    schema_created = fixture_created = False
    fixture_id = customer_id = None
    rows = [{} for _ in range(BUYERS)]
    baseline = original = None
    failure = None
    report = {"run": run, "buyers": BUYERS, "initial_stock": STOCK,
              "worker_autocommit": True, "separate_commit_duration_ms": None,
              "commit_measurement": "Not separately observable with the official implicit commit; see acknowledgement tails.",
              "source_sha256_before": source_hashes}
    try:
        expected_cluster = subprocess.check_output([
            "docker", "exec", "kloudkart_rebuild", "psql", "-X", "-U", "postgres", "-d", "postgres",
            "-qAt", "-c", "SELECT system_identifier::text FROM pg_control_system()"], text=True).strip()
        cur.execute("SELECT system_identifier::text FROM pg_control_system()")
        if cur.fetchone()[0] != expected_cluster:
            raise RuntimeError("Endpoint does not match named rebuilt container")
        cur.execute("SELECT current_setting('server_version'), current_setting('max_connections')")
        report["postgres_version"], report["max_connections"] = cur.fetchone()
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'")
        report["other_client_connections_before"] = cur.fetchone()[0]
        baseline = counts(cur)
        original = fingerprint(cur)
        cur.execute("SELECT prosrc FROM pg_proc WHERE oid='public.place_order(bigint,bigint,integer)'::regprocedure")
        database_body = cur.fetchone()[0]
        source_body = source_paths[1].read_text(encoding="utf-8-sig").split("$$")[1]
        def normalized(body):
            return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", body)).strip()
        report["public_function_body_matches_inspected_source"] = normalized(database_body) == normalized(source_body)
        if not report["public_function_body_matches_inspected_source"]:
            raise RuntimeError("Database checkout differs from the inspected source")
        checks = fixture_checks(cur)
        emit(safety_path, {"phase": "before", "counts": baseline, "fixture_checks": checks,
                           "fingerprints": original})
        if checks[1][0]["remaining_fixtures"] != 0:
            raise RuntimeError("Existing synthetic fixtures require investigation before proceeding")
        if any(checks[2][0].values()):
            raise RuntimeError("Candidate fixture has historical references")
        cur.execute("SELECT min(customer_id) FROM public.customers")
        customer_id = cur.fetchone()[0]
        if customer_id is None:
            raise RuntimeError("No valid customer available")
        cur.execute("SELECT coalesce(max(product_id),0)+1100 FROM public.products")
        fixture_id = cur.fetchone()[0]

        # Commit schema creation separately so partial installation can be cleaned.
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        schema_created = True
        diagnostic_sql = (HERE / "place_order_timed.sql").read_text(encoding="utf-8")
        diagnostic_sql = diagnostic_sql.replace("__DIAGNOSTIC_SCHEMA__", sql.Identifier(schema).as_string(conn))
        (LOGS / f"place_order_timed_{run}.sql").write_text(diagnostic_sql, encoding="utf-8")
        cur.execute(diagnostic_sql)
        cur.execute("""INSERT INTO public.products
            (product_id, product_name, category_id, price, stock_quantity, created_at)
            VALUES (%s,%s,NULL,100.00,%s,now())""", (fixture_id, fixture_name, STOCK))
        fixture_created = True
        before_clock = clock_calibration(cur)
        checkout_sql = sql.SQL("SELECT * FROM {}.place_order_timed(%s,%s,%s)").format(sql.Identifier(schema)).as_string(conn)
        release = {}

        def released():
            release["at"] = time.perf_counter()

        barrier = threading.Barrier(BUYERS, action=released)

        def worker(index):
            worker_conn = None
            result = {"buyer_index": index, "success": None}
            try:
                opening = time.perf_counter()
                worker_conn = psycopg2.connect(dsn)
                worker_conn.autocommit = True
                result["connection_ms"] = (time.perf_counter() - opening) * 1000
                with worker_conn.cursor() as worker_cur:
                    barrier.wait(timeout=60)
                    started = time.perf_counter()
                    worker_cur.execute(checkout_sql, (customer_id, fixture_id, 1))
                    acknowledged = time.perf_counter()
                    row = worker_cur.fetchone()
                    fetched = time.perf_counter()
                    if row is None:
                        raise RuntimeError("Diagnostic function returned no row")
                    data = dict(zip([entry.name for entry in worker_cur.description], row))
                    result.update({key: data[key] for key in FIELDS})
                    result.update({"success": data["success"],
                                   "refused_out_of_stock": not data["success"] and "out of stock" in data["message"].lower(),
                                   "client_execute_ms": (acknowledged - started) * 1000,
                                   "client_execute_fetch_ms": (fetched - started) * 1000,
                                   "transaction_idle_after_checkout": worker_conn.get_transaction_status() == extensions.TRANSACTION_STATUS_IDLE,
                                   "_ack_monotonic": acknowledged,
                                   "_stock_completed_epoch": data["stock_completed_epoch"],
                                   "_function_finished_epoch": data["function_finished_epoch"]})
                    # Deliberately no conn.commit(): official workers autocommit.
            except Exception as exc:
                result["error"] = exception_tag(exc)
                barrier.abort()
            finally:
                if worker_conn is not None:
                    worker_conn.close()
                rows[index] = result

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(BUYERS)]
        started = time.perf_counter()
        started_threads = []
        try:
            for thread in threads:
                thread.start()
                started_threads.append(thread)
        finally:
            if len(started_threads) != BUYERS:
                barrier.abort()
            for thread in started_threads:
                thread.join()
        finished = time.perf_counter()
        after_clock = clock_calibration(cur)
        report.update({"wall_seconds": finished - started,
                       "before_barrier_seconds": release.get("at", finished) - started,
                       "after_barrier_seconds": finished - release.get("at", finished),
                       "clock_calibration_before": before_clock, "clock_calibration_after": after_clock})
        # Envelope of pre/post offset brackets. Assumes no transient clock steps
        # during this short run; it is not a bound on arbitrary clock adjustments.
        low = min(before_clock["offset_low_s"], after_clock["offset_low_s"])
        high = max(before_clock["offset_high_s"], after_clock["offset_high_s"])
        report["clock_offset_envelope_width_ms"] = (high - low) * 1000
        for result in rows:
            if "_ack_monotonic" in result:
                for metric, timestamp in (("post_function_to_ack", "_function_finished_epoch"),
                                          ("stock_completed_to_ack", "_stock_completed_epoch")):
                    base = result["_ack_monotonic"] - result[timestamp]
                    result[metric + "_estimated_ms"] = (base + (low + high) / 2) * 1000
                    result[metric + "_low_ms"] = (base + low) * 1000
                    result[metric + "_high_ms"] = (base + high) * 1000
                for key in [key for key in result if key.startswith("_")]:
                    del result[key]
                result["before_stock_update_ms"] = (result["function_ms"] - result["stock_update_ms"]
                                                     - result["post_update_function_ms"])
                # For successful updates only, these bracket completion-to-commit
                # (subject to the clock assumptions). They exclude lock residence
                # inside UPDATE and are not exact total row-lock holding times.
                if result["success"]:
                    result["post_update_to_commit_lower_bound_ms"] = result["post_update_function_ms"]
                    result["post_update_to_commit_upper_bound_ms"] = result["stock_completed_to_ack_high_ms"]
            emit(results_path, result)
        good = [r for r in rows if r.get("success") is True and "error" not in r]
        refused = [r for r in rows if r.get("success") is False and "error" not in r]
        report.update({"successful_purchases": len(good), "refused_purchases": len(refused),
                       "errors": sum("error" in r for r in rows),
                       "all_refusals_out_of_stock": all(r["refused_out_of_stock"] for r in refused),
                       "all_checkout_transactions_idle_after_execute": all(r.get("transaction_idle_after_checkout") for r in good + refused)})
        metrics = FIELDS + ("client_execute_fetch_ms", "connection_ms", "post_function_to_ack_estimated_ms",
                           "stock_completed_to_ack_estimated_ms", "post_function_to_ack_low_ms", "post_function_to_ack_high_ms",
                           "before_stock_update_ms", "post_update_to_commit_lower_bound_ms", "post_update_to_commit_upper_bound_ms")
        report["timings"] = {label: {name: describe(r.get(name) for r in group) for name in metrics}
                             for label, group in (("successful", good), ("refused", refused))}
        cur.execute("SELECT stock_quantity FROM public.products WHERE product_id=%s AND product_name=%s", (fixture_id, fixture_name))
        report["final_stock"] = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT order_id), count(*) FROM public.order_items WHERE product_id=%s", (fixture_id,))
        report["fixture_orders"], report["fixture_order_items"] = cur.fetchone()
        cur.execute("SELECT count(*), coalesce(sum(change_qty),0) FROM public.inventory_log WHERE product_id=%s", (fixture_id,))
        report["fixture_inventory_rows"], report["fixture_inventory_net_change"] = cur.fetchone()
        actual = counts(cur)
        expected = dict(baseline)
        for table, increment in (("products", 1), ("orders", len(good)), ("order_items", len(good)), ("inventory_log", len(good))):
            expected[table] += increment
        emit(safety_path, {"phase": "after_workload_before_cleanup", "counts": actual,
                           "only_expected_count_increments": actual == expected})
        report["workload_counts_match_expected"] = actual == expected
        if not (len(good) == 50 and len(refused) == 350 and report["errors"] == 0
                and report["final_stock"] == 0 and report["fixture_orders"] == 50
                and report["fixture_order_items"] == 50 and report["fixture_inventory_rows"] == 50
                and report["fixture_inventory_net_change"] == -50 and actual == expected
                and report["all_refusals_out_of_stock"] and report["all_checkout_transactions_idle_after_execute"]):
            raise RuntimeError("Workload validation failed; inspect aggregate logs")
    except Exception as exc:
        failure = exception_tag(exc)
        report["investigation_error"] = failure
    finally:
        # Workers have joined before this point. Cleanup is one atomic transaction,
        # scoped to the exact fixture ID AND unique name, never a prefix wildcard.
        try:
            if fixture_created:
                conn.autocommit = False
                cur.execute("SELECT 1 FROM public.products WHERE product_id=%s AND product_name=%s FOR UPDATE", (fixture_id, fixture_name))
                if cur.fetchone() is None:
                    raise RuntimeError("Fixture ownership check failed; cleanup refused")
                cur.execute("SELECT DISTINCT order_id FROM public.order_items WHERE product_id=%s", (fixture_id,))
                own_orders = [row[0] for row in cur.fetchall()]
                if own_orders:
                    cur.execute("SELECT count(*) FROM public.order_items WHERE order_id=ANY(%s) AND product_id<>%s", (own_orders, fixture_id))
                    if cur.fetchone()[0]:
                        raise RuntimeError("Unexpected shared order; cleanup refused")
                cur.execute("DELETE FROM public.order_items WHERE product_id=%s", (fixture_id,))
                removed = {"order_items": cur.rowcount}
                if own_orders:
                    cur.execute("DELETE FROM public.orders WHERE order_id=ANY(%s)", (own_orders,))
                    removed["orders"] = cur.rowcount
                else:
                    removed["orders"] = 0
                cur.execute("DELETE FROM public.inventory_log WHERE product_id=%s", (fixture_id,))
                removed["inventory_log"] = cur.rowcount
                cur.execute("DELETE FROM public.products WHERE product_id=%s AND product_name=%s", (fixture_id, fixture_name))
                removed["products"] = cur.rowcount
                conn.commit()
                conn.autocommit = True
                report["fixture_rows_removed"] = removed
            if schema_created:
                # No CASCADE: unexpected objects prevent schema deletion.
                cur.execute(sql.SQL("DROP FUNCTION IF EXISTS {}.place_order_timed(bigint,bigint,integer)").format(sql.Identifier(schema)))
                cur.execute(sql.SQL("DROP SCHEMA {}").format(sql.Identifier(schema)))
            after = counts(cur)
            post_checks = fixture_checks(cur)
            after_fingerprint = fingerprint(cur)
            cur.execute("SELECT count(*) FROM pg_namespace WHERE nspname=%s", (schema,))
            report.update({"historical_counts_before": baseline, "historical_counts_after": after,
                           "historical_counts_restored": baseline is not None and after == baseline,
                           "diagnostic_schema_removed": cur.fetchone()[0] == 0,
                           "public_objects_unchanged": original is not None and original == after_fingerprint,
                           "source_sha256_after": {str(p.relative_to(ROOT)): digest(p) for p in source_paths}})
            report["protected_source_files_unchanged"] = source_hashes == report["source_sha256_after"]
            report["remaining_fixtures"] = post_checks[1][0]["remaining_fixtures"]
            emit(safety_path, {"phase": "after_cleanup", "counts": after, "fixture_checks": post_checks,
                               "fingerprints": after_fingerprint,
                               "diagnostic_schema_removed": report["diagnostic_schema_removed"]})
            if not (report["historical_counts_restored"] and report["diagnostic_schema_removed"]
                    and report["public_objects_unchanged"] and report["protected_source_files_unchanged"]
                    and report["remaining_fixtures"] == 0):
                raise RuntimeError("Post-cleanup verification failed")
        except Exception as exc:
            conn.rollback()
            report["cleanup_error"] = exception_tag(exc)
            failure = report["cleanup_error"]
        finally:
            cur.close()
            conn.close()
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"output_log": str(output_path.relative_to(ROOT)), "results_log": str(results_path.relative_to(ROOT)),
                          "safety_log": str(safety_path.relative_to(ROOT)),
                          "wall_seconds": report.get("wall_seconds"), "successful": report.get("successful_purchases"),
                          "refused": report.get("refused_purchases"), "errors": report.get("errors"),
                          "cleanup_ok": report.get("historical_counts_restored") and report.get("diagnostic_schema_removed"),
                          "investigation_error": report.get("investigation_error"), "cleanup_error": report.get("cleanup_error")}, indent=2))
    return 1 if failure else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"startup_error": exception_tag(exc)}))
        raise SystemExit(1) from None
