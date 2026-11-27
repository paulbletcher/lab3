-- Catalog price rejection tests. All product fixtures are synthetic and rolled back.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SELECT 'lab_catalog_price_' || gen_random_uuid()::text AS fixture_marker \gset

BEGIN;

CREATE TEMP TABLE catalog_price_run ON COMMIT DROP AS
SELECT :'fixture_marker'::text AS marker,
       (SELECT MIN(customer_id)::bigint FROM customers) AS customer_id;

CREATE TEMP TABLE catalog_price_fixtures (
    test_id text PRIMARY KEY,
    scenario text,
    price numeric(12,2),
    product_id integer
) ON COMMIT DROP;

INSERT INTO catalog_price_fixtures (test_id, scenario, price) VALUES
    ('VAL-08', 'NULL catalog price', NULL),
    ('VAL-09', 'Zero catalog price', 0),
    ('VAL-10', 'Negative catalog price', -1);

DO $$
DECLARE
    v_fixture record;
    v_candidate bigint := -2147483648;
    v_inserted integer;
BEGIN
    IF (SELECT customer_id FROM catalog_price_run) IS NULL THEN
        RAISE EXCEPTION 'An existing customer is required for catalog price tests';
    END IF;

    FOR v_fixture IN SELECT * FROM catalog_price_fixtures ORDER BY test_id LOOP
        LOOP
            IF v_candidate > 2147483647 THEN
                RAISE EXCEPTION 'No unused integer product ID is available';
            END IF;

            -- Retry occupied IDs without updating or deleting existing products.
            INSERT INTO products (product_id, product_name, price, stock_quantity)
            VALUES (v_candidate::integer,
                    (SELECT marker FROM catalog_price_run) || ':' || v_fixture.test_id,
                    v_fixture.price, 10)
            ON CONFLICT (product_id) DO NOTHING
            RETURNING product_id INTO v_inserted;

            EXIT WHEN FOUND;
            v_candidate := v_candidate + 1;
        END LOOP;

        UPDATE catalog_price_fixtures SET product_id = v_inserted
        WHERE test_id = v_fixture.test_id;
        v_candidate := v_candidate + 1;
    END LOOP;
END;
$$;

CREATE TEMP TABLE catalog_price_results ON COMMIT DROP AS
SELECT f.test_id, f.scenario, 'Invalid product price'::text AS expected_message,
       r.response_rows, r.success, r.order_id, r.actual_message,
       CASE WHEN r.response_rows = 1 AND r.matches_expected IS TRUE
            THEN 'PASS' ELSE 'FAIL' END AS test_result
FROM catalog_price_fixtures AS f
CROSS JOIN catalog_price_run AS c
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS response_rows,
           BOOL_AND(o.success) AS success,
           MIN(o.order_id) AS order_id,
           MIN(o.message) AS actual_message,
           BOOL_AND(o.success IS FALSE AND o.order_id IS NULL
                    AND o.message IS NOT DISTINCT FROM 'Invalid product price')
               AS matches_expected
    FROM place_order(c.customer_id, f.product_id::bigint, 1) AS o
) AS r;

SELECT * FROM catalog_price_results ORDER BY test_id;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM catalog_price_results) <> 3
       OR EXISTS (
           SELECT 1 FROM catalog_price_results
           WHERE test_result IS DISTINCT FROM 'PASS'
       ) THEN
        RAISE EXCEPTION 'Catalog price validation assertions failed';
    END IF;
END;
$$;

ROLLBACK;

-- The unique marker survives only in this psql variable, outside the transaction.
SELECT COUNT(*) AS remaining_synthetic_fixtures,
       COUNT(*) = 0 AS cleanup_ok
FROM products
WHERE product_name LIKE :'fixture_marker' || ':%'
\gset

\echo Remaining synthetic fixtures: :remaining_synthetic_fixtures
\if :cleanup_ok
    \echo Fixture cleanup: PASS
\else
    \echo Fixture cleanup: FAIL
    \quit 1
\endif
