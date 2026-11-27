-- Controlled experiment 1: per-product transaction advisory queue.

-- Phase 2: Transactional checkout function
-- Purpose: Place an order while preventing stock from becoming negative.
--
-- Stock deduction, order creation, order-item creation and inventory
-- logging must succeed or fail together within one transaction.

CREATE OR REPLACE FUNCTION public.place_order(
    p_customer_id bigint,
    p_product_id bigint,
    p_quantity integer
)
RETURNS TABLE (
    success boolean,
    order_id bigint,
    message text
)
LANGUAGE plpgsql
AS $$

DECLARE
    v_unit_price numeric(12,2);
    v_stock_quantity integer;
    v_new_order_id bigint;

BEGIN

    -- 1. Validate required inputs.
    IF p_customer_id IS NULL
       OR p_product_id IS NULL
       OR p_quantity IS NULL
       OR p_quantity <= 0 THEN

        RETURN QUERY
        SELECT FALSE, NULL::bigint, 'Invalid checkout input.'::text;
        RETURN;
    END IF;


    -- Phase 3 experiment 1: queue calls before touching the hot product row.
    -- Reserve the two-int advisory namespace 1145385011 for checkout product IDs.
    -- Transaction scope releases this lock on commit/rollback, including errors.
    -- Guard the cast because the public API accepts bigint but product PK is int.
    -- Keep the conditional UPDATE: writers outside this protocol remain safe.
    IF p_product_id BETWEEN -2147483648 AND 2147483647 THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(1145385011, p_product_id::integer);
    END IF;

    -- 2. Confirm that the customer exists.
    IF NOT EXISTS (
        SELECT 1
        FROM public.customers AS c
        WHERE c.customer_id = p_customer_id
    ) THEN

        RETURN QUERY
        SELECT FALSE, NULL::bigint, 'Customer not found.'::text;
        RETURN;
    END IF;


    -- 3. Atomically check and deduct available stock.
    -- PostgreSQL handles competing updates through row-level locking.
    UPDATE public.products AS p
    SET stock_quantity = p.stock_quantity - p_quantity
    WHERE p.product_id = p_product_id
      AND p.stock_quantity >= p_quantity
      AND p.price IS NOT NULL
      AND p.price >= 0
    RETURNING p.price
    INTO v_unit_price;


    -- 4. Handle failed stock deduction.
    IF NOT FOUND THEN

        SELECT p.stock_quantity, p.price
        INTO v_stock_quantity, v_unit_price
        FROM public.products AS p
        WHERE p.product_id = p_product_id;

        IF NOT FOUND THEN

            RETURN QUERY
            SELECT FALSE, NULL::bigint, 'Product not found.'::text;

        ELSIF v_unit_price IS NULL OR v_unit_price < 0 THEN

            RETURN QUERY
            SELECT FALSE, NULL::bigint, 'Invalid product price.'::text;

        ELSE

            RETURN QUERY
            SELECT FALSE, NULL::bigint, 'Out of stock.'::text;

        END IF;

        RETURN;
    END IF;


    -- 5. Create the order.
    -- Pending is used because this function does not process payment.
    INSERT INTO public.orders AS o (
        customer_id,
        order_date,
        status,
        total_amount
    )
    VALUES (
        p_customer_id,
        CURRENT_TIMESTAMP,
        'pending',
        v_unit_price * p_quantity
    )
    RETURNING o.order_id
    INTO v_new_order_id;


    -- 6. Create the order item.
    INSERT INTO public.order_items (
        order_id,
        product_id,
        quantity,
        unit_price
    )
    VALUES (
        v_new_order_id,
        p_product_id,
        p_quantity,
        v_unit_price
    );


    -- 7. Record the stock movement.
    INSERT INTO public.inventory_log (
        product_id,
        change_qty,
        reason,
        created_at,
        note
    )
    VALUES (
        p_product_id,
        -p_quantity,
        'sale',
        CURRENT_TIMESTAMP,
        'Sale recorded for order ID ' || v_new_order_id
    );


    -- 8. Return successful checkout details.
    RETURN QUERY
    SELECT
        TRUE,
        v_new_order_id,
        'Order placed successfully.'::text;

    RETURN;

END;
$$;
