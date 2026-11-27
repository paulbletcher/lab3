-- Final checkout: validate the latest balance under a product row lock.
-- Tested with the unchanged harness: 9.29, 7.98 and 7.54 seconds for 400 attempts.
-- The verified client uses Linux TCP with SCRAM password authentication.
-- Lock, stock deduction, order, item and audit remain one caller transaction.
-- Earlier conditional-update implementation is preserved in Git and test backups.

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
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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


    -- 3. Queue on the product row before validating its current balance.
    -- READ COMMITTED returns the latest row after an earlier owner commits.
    SELECT p.price, p.stock_quantity
    INTO v_unit_price, v_stock_quantity
    FROM public.products AS p
    WHERE p.product_id = p_product_id
    FOR NO KEY UPDATE;

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE,NULL::bigint,'Product not found.'::text;
        RETURN;
    ELSIF v_unit_price IS NULL OR v_unit_price < 0 THEN
        RETURN QUERY SELECT FALSE,NULL::bigint,'Invalid product price.'::text;
        RETURN;
    ELSIF v_stock_quantity IS NULL OR v_stock_quantity < p_quantity THEN
        RETURN QUERY SELECT FALSE,NULL::bigint,'Out of stock.'::text;
        RETURN;
    END IF;

    -- 4. Deduct only after locking and validating the current product row.
    -- Retain the stock predicate as defense in depth. The row lock lasts to commit.
    UPDATE public.products AS p
    SET stock_quantity = p.stock_quantity - p_quantity
    WHERE p.product_id = p_product_id AND p.stock_quantity >= p_quantity;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Locked product stock unexpectedly changed';
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
