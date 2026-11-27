-- Permanent stock refusal tests; fixtures and all test changes are rolled back.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SELECT 'lab_stock_' || gen_random_uuid()::text AS fixture_marker \gset
BEGIN;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '10s';
SHOW transaction_isolation;

CREATE TEMP TABLE stock_run ON COMMIT DROP AS
SELECT :'fixture_marker'::text AS marker,
       (SELECT MIN(customer_id)::bigint FROM customers) AS customer_id;

CREATE TEMP TABLE stock_fixtures (
    test_id text PRIMARY KEY,
    scenario text,
    stock_quantity integer,
    quantity integer,
    expected_message text,
    product_id integer
) ON COMMIT DROP;

INSERT INTO stock_fixtures
    (test_id, scenario, stock_quantity, quantity, expected_message) VALUES
    ('STOCK-01', 'NULL stock', NULL, 1, 'Stock quantity unavailable'),
    ('STOCK-02', 'Negative stock', -1, 1, 'Invalid stock quantity'),
    ('STOCK-03', 'Zero stock', 0, 1, 'Product out of stock'),
    ('STOCK-04', 'Positive insufficient stock', 2, 3, 'Product out of stock');

DO $$
DECLARE
    v_fixture record;
    v_candidate bigint := -2147483648;
    v_inserted integer;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Stock tests require the default READ COMMITTED isolation';
    END IF;
    IF (SELECT customer_id FROM stock_run) IS NULL THEN
        RAISE EXCEPTION 'An existing customer is required for stock tests';
    END IF;

    FOR v_fixture IN SELECT * FROM stock_fixtures ORDER BY test_id LOOP
        LOOP
            IF v_candidate > 2147483647 THEN
                RAISE EXCEPTION 'No unused integer product ID is available';
            END IF;
            INSERT INTO products (product_id, product_name, price, stock_quantity)
            VALUES (v_candidate::integer,
                    (SELECT marker FROM stock_run) || ':' || v_fixture.test_id,
                    12.50, v_fixture.stock_quantity)
            ON CONFLICT (product_id) DO NOTHING
            RETURNING product_id INTO v_inserted;
            EXIT WHEN FOUND;
            v_candidate := v_candidate + 1;
        END LOOP;
        UPDATE stock_fixtures SET product_id = v_inserted
        WHERE test_id = v_fixture.test_id;
        v_candidate := v_candidate + 1;
    END LOOP;
END;
$$;

-- Fingerprint every row, including existing records, without printing their data.
CREATE TEMP VIEW stock_business_state AS
SELECT 'products'::text AS table_name, COUNT(*) AS row_count,
       md5(COALESCE(string_agg(md5(row_to_json(p)::text), '' ORDER BY product_id), '')) AS fingerprint
FROM products AS p
UNION ALL
SELECT 'orders', COUNT(*),
       md5(COALESCE(string_agg(md5(row_to_json(o)::text), '' ORDER BY order_id), ''))
FROM orders AS o
UNION ALL
SELECT 'order_items', COUNT(*),
       md5(COALESCE(string_agg(md5(row_to_json(i)::text), '' ORDER BY order_item_id), ''))
FROM order_items AS i
UNION ALL
SELECT 'inventory_log', COUNT(*),
       md5(COALESCE(string_agg(md5(row_to_json(l)::text), '' ORDER BY log_id), ''))
FROM inventory_log AS l;

CREATE TEMP TABLE stock_before ON COMMIT DROP AS
SELECT * FROM stock_business_state;

CREATE TEMP TABLE stock_results ON COMMIT DROP AS
SELECT f.test_id, f.scenario, f.expected_message,
       r.response_rows, r.success, r.order_id, r.actual_message,
       CASE WHEN r.response_rows = 1 AND r.matches_expected IS TRUE
            THEN 'PASS' ELSE 'FAIL' END AS test_result
FROM stock_fixtures AS f
CROSS JOIN stock_run AS c
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS response_rows,
           BOOL_AND(o.success) AS success,
           MIN(o.order_id) AS order_id,
           MIN(o.message) AS actual_message,
           BOOL_AND(o.success IS FALSE AND o.order_id IS NULL
                    AND o.message IS NOT DISTINCT FROM f.expected_message) AS matches_expected
    FROM place_order(c.customer_id, f.product_id::bigint, f.quantity) AS o
) AS r;

SELECT * FROM stock_results ORDER BY test_id;

CREATE TEMP TABLE stock_after ON COMMIT DROP AS
SELECT * FROM stock_business_state;

SELECT b.table_name,
       CASE WHEN b.row_count = a.row_count AND b.fingerprint = a.fingerprint
            THEN 'PASS' ELSE 'FAIL' END AS unchanged
FROM stock_before AS b JOIN stock_after AS a USING (table_name)
ORDER BY b.table_name;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM stock_results) <> 4
       OR EXISTS (SELECT 1 FROM stock_results WHERE test_result <> 'PASS') THEN
        RAISE EXCEPTION 'Stock validation assertions failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM stock_before AS b JOIN stock_after AS a USING (table_name)
        WHERE b.row_count <> a.row_count OR b.fingerprint IS DISTINCT FROM a.fingerprint
    ) THEN
        RAISE EXCEPTION 'Checkout changed business data';
    END IF;
END;
$$;

ROLLBACK;

SELECT COUNT(*) AS remaining_synthetic_fixtures, COUNT(*) = 0 AS cleanup_ok
FROM products
WHERE left(product_name, length(:'fixture_marker') + 1) = :'fixture_marker' || ':'
\gset
\echo Remaining synthetic stock fixtures: :remaining_synthetic_fixtures
\if :cleanup_ok
    \echo Fixture cleanup: PASS
\else
    \echo Fixture cleanup: FAIL
    \quit 1
\endif
