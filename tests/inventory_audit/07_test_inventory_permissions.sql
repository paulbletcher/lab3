-- Phase 3: Test restricted application permissions.
-- All synthetic records are rolled back.

BEGIN;

-- Create a synthetic product as the administrator.
SELECT GREATEST(
    COALESCE((SELECT MAX(product_id) FROM public.products), 0),
    COALESCE((SELECT MAX(product_id) FROM public.inventory_log), 0),
    COALESCE((SELECT MAX(product_id) FROM public.order_items), 0)
) + 1000 AS fixture_id
\gset

SELECT MIN(customer_id) AS fixture_customer_id
FROM public.customers
\gset

INSERT INTO public.products (
    product_id,
    product_name,
    price,
    stock_quantity,
    created_at
)
VALUES (
    :fixture_id,
    'INVENTORY PERMISSIONS TEST FIXTURE',
    100.00,
    20,
    CURRENT_TIMESTAMP
);

SELECT set_config(
    'kloudkart.test_product_id',
    :'fixture_id',
    TRUE
);

SELECT set_config(
    'kloudkart.test_customer_id',
    :'fixture_customer_id',
    TRUE
);

-- Switch to the restricted application role.
SET LOCAL ROLE kloudkart_app;

SELECT current_user AS active_role;

DO $test$

DECLARE
    v_product_id integer;
    v_customer_id bigint;
    v_stock integer;
    v_log_id integer;
    v_success boolean;
    v_order_id bigint;
    v_message text;
    v_test record;

BEGIN

    v_product_id :=
        current_setting('kloudkart.test_product_id')::integer;

    v_customer_id :=
        current_setting('kloudkart.test_customer_id')::bigint;


    -- Tests 1-9: Direct access must be denied.
    FOR v_test IN

        SELECT *
        FROM (
            VALUES
                (1, 'Direct stock update',
                    'UPDATE public.products SET stock_quantity = 999 WHERE product_id = %s'),

                (2, 'Direct audit insertion',
                    'INSERT INTO public.inventory_log (product_id, change_qty, reason) VALUES (%s, 10, ''restock'')'),

                (3, 'Direct audit modification',
                    'UPDATE public.inventory_log SET change_qty = 999 WHERE product_id = %s'),

                (4, 'Direct audit deletion',
                    'DELETE FROM public.inventory_log WHERE product_id = %s'),

                (5, 'Direct product deletion',
                    'DELETE FROM public.products WHERE product_id = %s'),

                (6, 'Direct product insertion',
                    'INSERT INTO public.products (product_id, stock_quantity) VALUES (%s, 100)'),

                (7, 'Direct sequence access',
                    'SELECT nextval(''public.inventory_log_log_id_seq'')'),

                (8, 'Direct order insertion',
                    'INSERT INTO public.orders (customer_id) VALUES (%s)'),

                (9, 'Direct product reading',
                    'SELECT stock_quantity FROM public.products WHERE product_id = %s')

        ) AS t (test_number, description, statement)
        ORDER BY test_number

    LOOP

        BEGIN

            EXECUTE format(v_test.statement, v_product_id);

            RAISE EXCEPTION
                'FAIL Test %: % was allowed.',
                v_test.test_number,
                v_test.description;

        EXCEPTION
            WHEN insufficient_privilege THEN

                RAISE NOTICE
                    'PASS Test %: % denied.',
                    v_test.test_number,
                    v_test.description;

        END;

    END LOOP;


    -- Test 10: Approved inventory movement must succeed.
    SELECT
        m.new_stock_quantity,
        m.inventory_log_id
    INTO v_stock, v_log_id
    FROM public.record_inventory_movement(
        v_product_id,
        'restock',
        10,
        'Application permission test'
    ) AS m;

    IF v_stock IS DISTINCT FROM 30
        OR v_log_id IS NULL THEN

        RAISE EXCEPTION
            'FAIL Test 10: Approved inventory movement failed.';

    END IF;

    RAISE NOTICE
        'PASS Test 10: Approved restock succeeded. Stock = %.',
        v_stock;


    -- Test 11: Approved checkout must succeed.
    SELECT
        o.success,
        o.order_id,
        o.message
    INTO v_success, v_order_id, v_message
    FROM public.place_order(
        v_customer_id,
        v_product_id::bigint,
        7
    ) AS o;

    IF v_success IS DISTINCT FROM TRUE
        OR v_order_id IS NULL THEN

        RAISE EXCEPTION
            'FAIL Test 11: Checkout failed: %.', v_message;

    END IF;

    RAISE NOTICE
        'PASS Test 11: Approved checkout succeeded.';

END;

$test$;


-- Return to administrator privileges for independent verification.
RESET ROLE;

DO $verify$

DECLARE
    v_product_id integer;
    v_stock integer;
    v_log_count bigint;
    v_total_change bigint;
    v_restock_count bigint;
    v_sale_count bigint;
    v_order_count bigint;

BEGIN

    v_product_id :=
        current_setting('kloudkart.test_product_id')::integer;

    SELECT stock_quantity
    INTO v_stock
    FROM public.products
    WHERE product_id = v_product_id;

    SELECT
        COUNT(*),
        COALESCE(SUM(change_qty), 0),
        COUNT(*) FILTER (
            WHERE reason = 'restock' AND change_qty = 10
        ),
        COUNT(*) FILTER (
            WHERE reason = 'sale' AND change_qty = -7
        )
    INTO
        v_log_count,
        v_total_change,
        v_restock_count,
        v_sale_count
    FROM public.inventory_log
    WHERE product_id = v_product_id;

    SELECT COUNT(DISTINCT order_id)
    INTO v_order_count
    FROM public.order_items
    WHERE product_id = v_product_id;

    -- Test 12: Verify resulting database state.
    IF v_stock IS DISTINCT FROM 23
        OR v_log_count <> 2
        OR v_total_change <> 3
        OR v_restock_count <> 1
        OR v_sale_count <> 1
        OR v_order_count <> 1 THEN

        RAISE EXCEPTION
            'FAIL Test 12: Stock, orders or audit trail inconsistent.';

    END IF;

    RAISE NOTICE
        'PASS Test 12: Stock, orders and audit trail reconcile.';

    RAISE NOTICE 'Initial stock: 20';
    RAISE NOTICE 'Restock: +10';
    RAISE NOTICE 'Checkout: -7';
    RAISE NOTICE 'Final stock: %', v_stock;
    RAISE NOTICE 'Audit records: %', v_log_count;
    RAISE NOTICE 'Orders created: %', v_order_count;

    RAISE NOTICE 'ALL 12 APPLICATION PERMISSION TESTS PASSED.';

END;

$verify$;

ROLLBACK;
