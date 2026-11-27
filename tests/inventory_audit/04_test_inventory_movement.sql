-- Phase 3: Inventory audit
-- Test controlled inventory movements using a synthetic product.
-- Roll back all test records at the end.

BEGIN;

DO $test$

DECLARE
    v_product_id integer;
    v_stock integer;
    v_log_id integer;
    v_change_qty integer;
    v_reason text;
    v_log_count bigint;
    v_total_change bigint;
    v_test record;
    v_rejected boolean;
    v_error text;

BEGIN

    -- Create a synthetic product with an unused ID.
    SELECT GREATEST(
        COALESCE((SELECT MAX(product_id) FROM public.products), 0),
        COALESCE((SELECT MAX(product_id) FROM public.inventory_log), 0),
        COALESCE((SELECT MAX(product_id) FROM public.order_items), 0)
    ) + 1000
    INTO v_product_id;

    INSERT INTO public.products (
        product_id,
        product_name,
        price,
        stock_quantity,
        created_at
    )
    VALUES (
        v_product_id,
        'INVENTORY AUDIT TEST FIXTURE',
        100.00,
        20,
        CURRENT_TIMESTAMP
    );

    RAISE NOTICE 'Synthetic product created with stock of 20.';


    -- Tests 1-8: Successful inventory movements.
    FOR v_test IN

        SELECT *
        FROM (
            VALUES
                (1, 'restock',    10, FALSE, 30,  10),
                (2, 'return',      5, TRUE,  35,   5),
                (3, 'correction',  3, FALSE, 38,   3),
                (4, 'correction', -4, FALSE, 34,  -4),
                (5, 'damage',      6, FALSE, 28,  -6),
                (6, 'stock_take', 32, FALSE, 32,   4),
                (7, 'stock_take', 25, FALSE, 25,  -7),
                (8, 'stock_take', 25, FALSE, 25,   0)
        ) AS t (
            test_number,
            reason,
            quantity,
            inspection_approved,
            expected_stock,
            expected_change
        )
        ORDER BY test_number

    LOOP

        SELECT
            m.new_stock_quantity,
            m.inventory_log_id
        INTO v_stock, v_log_id
        FROM public.record_inventory_movement(
            v_product_id,
            v_test.reason,
            v_test.quantity,
            'Synthetic inventory movement test',
            v_test.inspection_approved
        ) AS m;

        -- Verify returned stock balance.
        IF v_stock IS DISTINCT FROM v_test.expected_stock THEN
            RAISE EXCEPTION
                'Test % failed: expected stock %, received %.',
                v_test.test_number,
                v_test.expected_stock,
                v_stock;
        END IF;

        -- Verify the actual stored stock balance.
        SELECT p.stock_quantity
        INTO v_stock
        FROM public.products AS p
        WHERE p.product_id = v_product_id;

        IF v_stock IS DISTINCT FROM v_test.expected_stock THEN
            RAISE EXCEPTION
                'Test % failed: stored stock is incorrect.',
                v_test.test_number;
        END IF;

        -- Verify the corresponding inventory audit record.
        SELECT il.change_qty, il.reason
        INTO v_change_qty, v_reason
        FROM public.inventory_log AS il
        WHERE il.log_id = v_log_id
            AND il.product_id = v_product_id
            AND il.created_at IS NOT NULL
            AND il.note IS NOT NULL;

        IF NOT FOUND
            OR v_change_qty IS DISTINCT FROM v_test.expected_change
            OR v_reason IS DISTINCT FROM v_test.reason THEN

            RAISE EXCEPTION
                'Test % failed: incorrect or missing audit record.',
                v_test.test_number;
        END IF;

        RAISE NOTICE
            'PASS Test %: %, stock = %, logged change = %.',
            v_test.test_number,
            v_test.reason,
            v_stock,
            v_change_qty;

    END LOOP;


    -- Tests 9-17: Invalid movements must be rejected.
    FOR v_test IN

        SELECT *
        FROM (
            VALUES
                (9,  'return',      5, FALSE, 'inspection'),
                (10, 'damage',     26, FALSE, 'Insufficient stock'),
                (11, 'invalid',     5, FALSE, 'Invalid inventory movement reason'),
                (12, 'restock',     0, FALSE, 'Quantity must be positive'),
                (13, 'restock',    -5, FALSE, 'Quantity must be positive'),
                (14, 'correction',  0, FALSE, 'Correction quantity cannot be zero'),
                (15, 'stock_take', -1, FALSE, 'cannot be negative'),
                (16, 'sale',        1, FALSE, 'Invalid inventory movement reason'),
                (17, 'return',      5, NULL,  'inspection')
        ) AS t (
            test_number,
            reason,
            quantity,
            inspection_approved,
            expected_error
        )
        ORDER BY test_number

    LOOP

        v_rejected := FALSE;

        BEGIN

            PERFORM public.record_inventory_movement(
                v_product_id,
                v_test.reason,
                v_test.quantity,
                'Invalid movement test',
                v_test.inspection_approved
            );

        EXCEPTION
            WHEN raise_exception THEN

                v_error := SQLERRM;

                IF strpos(v_error, v_test.expected_error) = 0 THEN
                    RAISE;
                END IF;

                v_rejected := TRUE;

        END;

        IF NOT v_rejected THEN
            RAISE EXCEPTION
                'Test % failed: invalid movement was accepted.',
                v_test.test_number;
        END IF;

        -- Rejected movements must not change stock.
        SELECT p.stock_quantity
        INTO v_stock
        FROM public.products AS p
        WHERE p.product_id = v_product_id;

        IF v_stock IS DISTINCT FROM 25 THEN
            RAISE EXCEPTION
                'Test % failed: rejected movement changed stock.',
                v_test.test_number;
        END IF;

        -- Rejected movements must not create audit records.
        SELECT COUNT(*)
        INTO v_log_count
        FROM public.inventory_log AS il
        WHERE il.product_id = v_product_id;

        IF v_log_count <> 8 THEN
            RAISE EXCEPTION
                'Test % failed: rejected movement created an audit record.',
                v_test.test_number;
        END IF;

        RAISE NOTICE
            'PASS Test %: rejected correctly — %.',
            v_test.test_number,
            v_error;

    END LOOP;


    -- Test 18: Nonexistent product.
    v_rejected := FALSE;

    BEGIN

        PERFORM public.record_inventory_movement(
            v_product_id + 1,
            'restock',
            5
        );

    EXCEPTION
        WHEN raise_exception THEN

            IF strpos(SQLERRM, 'does not exist') = 0 THEN
                RAISE;
            END IF;

            v_rejected := TRUE;

    END;

    IF NOT v_rejected THEN
        RAISE EXCEPTION
            'Test 18 failed: nonexistent product accepted.';
    END IF;

    RAISE NOTICE 'PASS Test 18: nonexistent product rejected.';


    -- Test 19: Reconcile final stock against the audit trail.
    SELECT
        COUNT(*),
        COALESCE(SUM(il.change_qty), 0)
    INTO v_log_count, v_total_change
    FROM public.inventory_log AS il
    WHERE il.product_id = v_product_id;

    SELECT p.stock_quantity
    INTO v_stock
    FROM public.products AS p
    WHERE p.product_id = v_product_id;

    IF v_log_count <> 8
        OR v_stock IS DISTINCT FROM 25
        OR v_stock IS DISTINCT FROM (20 + v_total_change) THEN

        RAISE EXCEPTION
            'Test 19 failed: stock and audit trail do not reconcile.';
    END IF;

    RAISE NOTICE 'PASS Test 19: stock and audit trail reconcile.';

    RAISE NOTICE 'Initial stock: 20';
    RAISE NOTICE 'Net inventory movement: %', v_total_change;
    RAISE NOTICE 'Final stock: %', v_stock;
    RAISE NOTICE 'Audit records: %', v_log_count;
    RAISE NOTICE 'ALL 19 INVENTORY MOVEMENT TESTS PASSED.';

END;

$test$;

-- Remove all synthetic test records.
ROLLBACK;