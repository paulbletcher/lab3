
-- Phase 2: Checkout function test
-- Purpose: Test successful purchases and insufficient-stock handling.
-- All test records are rolled back after verification.

BEGIN;

DO $$
DECLARE
    v_customer_id bigint;
    v_product_id integer;
    v_result record;
    v_stock integer;
    v_order_count integer;
    v_item_count integer;
    v_log_count integer;
BEGIN

    -- 1. Select an existing customer.
    SELECT MIN(customer_id)
    INTO v_customer_id
    FROM customers;

    IF v_customer_id IS NULL THEN
        RAISE EXCEPTION 'No customer available for testing.';
    END IF;

    -- 2. Generate an unused product ID for the test fixture.
    SELECT COALESCE(MAX(product_id), 0) + 1000
    INTO v_product_id
    FROM products;

    -- 3. Create a temporary product with two units in stock.
    INSERT INTO products (
        product_id,
        product_name,
        category_id,
        price,
        stock_quantity,
        created_at
    )
    VALUES (
        v_product_id,
        'PHASE2 CHECKOUT TEST',
        NULL,
        25.00,
        2,
        CURRENT_TIMESTAMP
    );

    -- 4. Test a successful purchase of one unit.
    SELECT *
    INTO v_result
    FROM place_order(v_customer_id, v_product_id, 1);

    IF v_result.success IS NOT TRUE THEN
        RAISE EXCEPTION 'Purchase failed: %', v_result.message;
    END IF;

    RAISE NOTICE 'Successful purchase: order ID = %',
        v_result.order_id;

    -- 5. Verify remaining stock.
    SELECT stock_quantity
    INTO v_stock
    FROM products
    WHERE product_id = v_product_id;

    IF v_stock <> 1 THEN
        RAISE EXCEPTION 'Expected stock 1, found %', v_stock;
    END IF;

    -- 6. Verify order, order item and inventory log.
    SELECT COUNT(*) INTO v_order_count
    FROM orders
    WHERE order_id = v_result.order_id;

    SELECT COUNT(*) INTO v_item_count
    FROM order_items
    WHERE order_id = v_result.order_id
      AND product_id = v_product_id;

    SELECT COUNT(*) INTO v_log_count
    FROM inventory_log
    WHERE product_id = v_product_id
      AND change_qty = -1
      AND reason = 'sale';

    IF v_order_count <> 1
       OR v_item_count <> 1
       OR v_log_count <> 1 THEN
        RAISE EXCEPTION
            'Order, item or inventory log verification failed.';
    END IF;

    RAISE NOTICE 'Order, order item and inventory log verified.';

    -- 7. Attempt to purchase more units than remain.
    SELECT *
    INTO v_result
    FROM place_order(v_customer_id, v_product_id, 2);

    IF v_result.success IS NOT FALSE
       OR v_result.order_id IS NOT NULL
       OR v_result.message NOT ILIKE '%out of stock%' THEN
        RAISE EXCEPTION
            'Insufficient-stock test failed: %', v_result.message;
    END IF;

    -- 8. Confirm the refused purchase changed nothing.
    SELECT stock_quantity
    INTO v_stock
    FROM products
    WHERE product_id = v_product_id;

    IF v_stock <> 1 THEN
        RAISE EXCEPTION
            'Stock changed after refused purchase.';
    END IF;

    RAISE NOTICE 'Insufficient-stock request refused correctly.';
    RAISE NOTICE 'All checkout tests passed.';

END $$;

-- Remove temporary test records.
ROLLBACK;
