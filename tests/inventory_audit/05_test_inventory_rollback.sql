-- Phase 3: Inventory audit
-- Test atomic rollback when inventory log insertion fails.
-- All synthetic records and test constraints are rolled back.

BEGIN;

DO $test$

DECLARE
    v_product_id integer;
    v_stock integer;
    v_log_count bigint;
    v_rejected boolean := FALSE;
    v_constraint_name text;

BEGIN

    -- 1. Create a synthetic product with an unused ID.
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
        'INVENTORY ROLLBACK TEST FIXTURE',
        100.00,
        20,
        CURRENT_TIMESTAMP
    );

    RAISE NOTICE 'Initial stock: 20';


    -- 2. Introduce a test constraint that prevents audit
    -- records from being inserted for this synthetic product.
    EXECUTE format(
        'ALTER TABLE public.inventory_log
         ADD CONSTRAINT test_inventory_audit_failure
         CHECK (product_id <> %s) NOT VALID',
        v_product_id
    );

    RAISE NOTICE 'Audit failure constraint installed.';


    -- 3. Attempt an otherwise valid restock operation.
    BEGIN

        PERFORM public.record_inventory_movement(
            v_product_id,
            'restock',
            10,
            'Forced audit insertion failure test'
        );

    EXCEPTION
        WHEN check_violation THEN

            GET STACKED DIAGNOSTICS
                v_constraint_name = CONSTRAINT_NAME;

            -- Confirm that our intended constraint caused the failure.
            IF v_constraint_name IS DISTINCT FROM
                'test_inventory_audit_failure' THEN

                RAISE;

            END IF;

            v_rejected := TRUE;

            RAISE NOTICE
                'PASS: Expected audit insertion failure occurred.';

    END;


    -- 4. Verify that the operation failed.
    IF NOT v_rejected THEN

        RAISE EXCEPTION
            'FAIL: Movement unexpectedly succeeded.';

    END IF;


    -- 5. Verify that the stock adjustment was rolled back.
    SELECT p.stock_quantity
    INTO v_stock
    FROM public.products AS p
    WHERE p.product_id = v_product_id;

    IF v_stock IS DISTINCT FROM 20 THEN

        RAISE EXCEPTION
            'FAIL: Expected stock of 20, found %.', v_stock;

    END IF;

    RAISE NOTICE 'PASS: Stock adjustment rolled back.';
    RAISE NOTICE 'Stock after failure: %', v_stock;


    -- 6. Verify that no audit record was created.
    SELECT COUNT(*)
    INTO v_log_count
    FROM public.inventory_log AS il
    WHERE il.product_id = v_product_id;

    IF v_log_count <> 0 THEN

        RAISE EXCEPTION
            'FAIL: Unexpected audit records found: %.', v_log_count;

    END IF;

    RAISE NOTICE 'PASS: No partial audit records created.';
    RAISE NOTICE 'Audit records after failure: %', v_log_count;


    -- 7. Remove the test constraint.
    ALTER TABLE public.inventory_log
    DROP CONSTRAINT test_inventory_audit_failure;


    -- 8. Repeat the same movement without the constraint.
    -- This confirms the request itself was valid.
    PERFORM public.record_inventory_movement(
        v_product_id,
        'restock',
        10,
        'Recovery after forced audit failure'
    );


    -- 9. Verify successful recovery.
    SELECT p.stock_quantity
    INTO v_stock
    FROM public.products AS p
    WHERE p.product_id = v_product_id;

    SELECT COUNT(*)
    INTO v_log_count
    FROM public.inventory_log AS il
    WHERE il.product_id = v_product_id
        AND il.change_qty = 10
        AND il.reason = 'restock';

    IF v_stock IS DISTINCT FROM 30
        OR v_log_count <> 1 THEN

        RAISE EXCEPTION
            'FAIL: Movement did not recover correctly.';

    END IF;

    RAISE NOTICE 'PASS: Movement succeeds after constraint removal.';
    RAISE NOTICE 'Stock after recovery: %', v_stock;
    RAISE NOTICE 'Matching audit records after recovery: %', v_log_count;

    RAISE NOTICE 'ALL INVENTORY ROLLBACK CHECKS PASSED.';

END;

$test$;

-- Remove all synthetic records and transactional schema changes.
ROLLBACK;