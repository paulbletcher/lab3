"""Verify automatic IDs in a uniquely named disposable Docker database.

Run from the project root: python tests/verify_identity_migration.py
The existing postgres database is never passed to schema.sql or load.sql.
Only aggregate results are printed; captured loader errors are not displayed.
"""

import json
import subprocess
import uuid


CONTAINER = "kloudkart"
TEST_DB = "kloudkart_identity_test_" + uuid.uuid4().hex[:12]
TARGETS = [("orders", "order_id"), ("order_items", "order_item_id"),
           ("inventory_log", "log_id")]


def command(arguments, *, sql=None, expect_failure=False):
    result = subprocess.run(["docker", "exec", "-w", "/lab", "-i", CONTAINER,
                             *arguments], input=sql, text=True, capture_output=True)
    if (result.returncode != 0) != expect_failure:
        raise RuntimeError("Unexpected command status; server output withheld "
                           "to protect confidential source values.")
    return result.stdout


def psql(sql=None, *, file=None, expect_failure=False):
    arguments = ["psql", "-U", "postgres", "-d", TEST_DB, "-X", "-t", "-A",
                 "-v", "ON_ERROR_STOP=1"]
    if file:
        arguments += ["-f", file]
    return command(arguments, sql=sql, expect_failure=expect_failure).strip()


def metadata():
    return json.loads(psql("""
        SELECT json_agg(row_to_json(c) ORDER BY table_name)
        FROM (SELECT table_name, identity_generation,
                     pg_get_serial_sequence('public.' || table_name, column_name)
                         AS sequence_name,
                     pg_get_serial_sequence('public.' || table_name, column_name)::regclass::oid
                         AS sequence_oid
              FROM information_schema.columns
              WHERE table_schema = 'public'
                AND (table_name, column_name) IN
                    (('orders','order_id'), ('order_items','order_item_id'),
                     ('inventory_log','log_id'))) c;
    """))


def states():
    # These are the default names created in this disposable test database.
    parts = [f"SELECT '{table}' AS table_name, last_value, is_called "
             f"FROM public.{table}_{column}_seq" for table, column in TARGETS]
    return psql(" UNION ALL ".join(parts) + " ORDER BY table_name;")


def aggregates():
    return psql("""
        SELECT (SELECT count(*) FROM public.orders),
               (SELECT count(*) FROM public.order_items),
               (SELECT count(*) FROM public.inventory_log),
               (SELECT count(*) FROM public.order_items oi
                LEFT JOIN public.orders o USING (order_id) WHERE o.order_id IS NULL);
    """)


def migrate():
    psql(file="checkout.sql")
    assert all(c["identity_generation"] == "ALWAYS" for c in metadata())


def main():
    command(["createdb", "-U", "postgres", "--template=template0", TEST_DB])
    try:
        psql(file="schema.sql")
        psql(file="load.sql")
        assert all(c["identity_generation"] is None for c in metadata())
        psql(file="checkout_prechecks.sql")
        original_aggregates = aggregates()
        floors = json.loads(psql("""
            SELECT json_build_array(
                GREATEST((SELECT coalesce(max(order_id)::bigint,0) FROM public.orders),
                         (SELECT coalesce(max(order_id)::bigint,0) FROM public.order_items)) + 1,
                (SELECT coalesce(max(order_item_id)::bigint,0)+1 FROM public.order_items),
                (SELECT coalesce(max(log_id)::bigint,0)+1 FROM public.inventory_log));
        """))
        migrate()
        psql(file="checkout_prechecks.sql")
        for (table, column), floor in zip(TARGETS, floors):
            assert psql(f"SELECT last_value = {floor} AND NOT is_called "
                        f"FROM public.{table}_{column}_seq;") == "t"
        assert aggregates() == original_aggregates
        print("PASS: fresh original data load; ALWAYS identities; safe IDs "
              + ", ".join(map(str, floors)), flush=True)

        before = states(), metadata()
        migrate()
        assert (states(), metadata()) == before
        print("PASS: rerun preserves unused sequence states and object IDs", flush=True)

        # Synthetic inserts are rolled back; only the disposable sequences advance.
        statements = []
        for (table, column), floor in zip(TARGETS, floors):
            statements.append(f"""
                INSERT INTO public.{table} DEFAULT VALUES RETURNING {column} INTO generated;
                IF generated <> {floor} THEN RAISE EXCEPTION 'Unsafe generated ID'; END IF;
                BEGIN
                    INSERT INTO public.{table} ({column}) VALUES (-2147483000);
                    RAISE EXCEPTION 'ALWAYS accepted an explicit ID';
                EXCEPTION WHEN generated_always THEN NULL;
                END;
            """)
        psql("BEGIN; DO $test$ DECLARE generated bigint; BEGIN "
             + "\n".join(statements) + " END $test$; ROLLBACK;")
        assert aggregates() == original_aggregates
        before = states(), metadata()
        migrate()
        assert (states(), metadata()) == before
        print("PASS: generated inserts and explicit-ID rejection; "
              "rerun does not reuse issued IDs", flush=True)

        psql("\n".join(f"ALTER TABLE public.{t} ALTER COLUMN {c} SET GENERATED BY DEFAULT;"
                       for t, c in TARGETS))
        before = states()
        sequence_oids = [c["sequence_oid"] for c in metadata()]
        migrate()
        assert states() == before
        assert [c["sequence_oid"] for c in metadata()] == sequence_oids
        print("PASS: BY DEFAULT converts to ALWAYS without replacing sequences", flush=True)

        # Deliberately invalid states only in this disposable database. The early
        # order repair must roll back when the later cache validation fails.
        psql("ALTER SEQUENCE public.orders_order_id_seq RESTART WITH 1; "
             "ALTER SEQUENCE public.inventory_log_log_id_seq CACHE 2;")
        before = states(), metadata()
        psql(file="checkout.sql", expect_failure=True)
        assert (states(), metadata()) == before
        assert aggregates() == original_aggregates
        print("PASS: unexpected configuration aborts and forward repair rolls back", flush=True)
    finally:
        # The name is generated above, never supplied by the user or read from a DSN.
        command(["dropdb", "-U", "postgres", "--if-exists", TEST_DB])
        print("Removed disposable verification database", flush=True)


if __name__ == "__main__":
    main()
