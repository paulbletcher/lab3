-- Phase 2: Safe order placement.
-- Reserve stock and record a pending order, item and sale movement atomically.

CREATE OR REPLACE FUNCTION place_order(
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
    v_price products.price%TYPE;
    v_stock_quantity products.stock_quantity%TYPE;
    v_order_id orders.order_id%TYPE;
BEGIN

    -- Reject requests with missing parameters.
    IF p_customer_id IS NULL
       OR p_product_id IS NULL
       OR p_quantity IS NULL THEN

        RETURN QUERY
        SELECT false, NULL::bigint, 'Required input is missing'::text;

        RETURN;
    END IF;

    -- Purchase quantities must be strictly positive.
    IF p_quantity <= 0 THEN

        RETURN QUERY
        SELECT false, NULL::bigint, 'Quantity must be greater than zero'::text;

        RETURN;
    END IF;

    -- Protect the customer key before taking the product lock.
    PERFORM 1
    FROM customers AS c
    WHERE c.customer_id = p_customer_id
    FOR KEY SHARE;

    IF NOT FOUND THEN

        RETURN QUERY
        SELECT false, NULL::bigint, 'Customer not found'::text;

        RETURN;
    END IF;

    -- Lock the product and retrieve the current catalog price and stock together.
    SELECT p.price, p.stock_quantity
    INTO v_price, v_stock_quantity
    FROM products AS p
    WHERE p.product_id = p_product_id
    FOR UPDATE;

    IF NOT FOUND THEN

        RETURN QUERY
        SELECT false, NULL::bigint, 'Product not found'::text;

        RETURN;
    END IF;

    -- Catalog prices must be present and strictly positive.
    IF v_price IS NULL OR v_price <= 0 THEN

        RETURN QUERY
        SELECT false, NULL::bigint, 'Invalid product price'::text;

        RETURN;
    END IF;

    -- Unknown or corrupt stock cannot be used to approve a purchase.
    IF v_stock_quantity IS NULL THEN
        RETURN QUERY
        SELECT false, NULL::bigint, 'Stock quantity unavailable'::text;
        RETURN;
    END IF;

    IF v_stock_quantity < 0 THEN
        RETURN QUERY
        SELECT false, NULL::bigint, 'Invalid stock quantity'::text;
        RETURN;
    END IF;

    IF v_stock_quantity < p_quantity THEN
        RETURN QUERY
        SELECT false, NULL::bigint, 'Product out of stock'::text;
        RETURN;
    END IF;

    -- The row is already locked; keep a defensive availability predicate.
    UPDATE products AS p
    SET stock_quantity = p.stock_quantity - p_quantity
    WHERE p.product_id = p_product_id
      AND p.stock_quantity >= p_quantity
    RETURNING p.stock_quantity INTO v_stock_quantity;

    IF NOT FOUND THEN
        RETURN QUERY
        SELECT false, NULL::bigint, 'Product out of stock'::text;
        RETURN;
    END IF;

    -- Identities allocate IDs safely; payment is not confirmed by this function.
    INSERT INTO orders AS o (customer_id, order_date, status, total_amount)
    VALUES (p_customer_id, CURRENT_TIMESTAMP, 'pending', v_price * p_quantity)
    RETURNING o.order_id INTO v_order_id;

    INSERT INTO order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, p_product_id, p_quantity, v_price);

    INSERT INTO inventory_log (product_id, change_qty, reason, created_at, note)
    VALUES (p_product_id, -p_quantity, 'sale', CURRENT_TIMESTAMP,
            'Order ' || v_order_id::text);

    -- Errors propagate so the caller's transaction rolls back all four writes.
    RETURN QUERY
    SELECT true, v_order_id::bigint, 'Order placed successfully'::text;

END;
$$;

