-- Phase 2: Safe order placement.
-- Validate the basic checkout parameters.

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

    -- Reject requests from nonexistent customers.
    IF NOT EXISTS (
        SELECT 1
        FROM customers AS c
        WHERE c.customer_id = p_customer_id
    ) THEN

        RETURN QUERY
        SELECT false, NULL::bigint, 'Customer not found'::text;

        RETURN;
    END IF;

    -- Retrieve the catalog price and distinguish absent products from NULL prices.
    SELECT p.price INTO v_price
    FROM products AS p
    WHERE p.product_id = p_product_id;

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

    -- Temporary response until the remaining checkout logic is implemented.
    RETURN QUERY
    SELECT false, NULL::bigint, 'Checkout not implemented'::text;

END;
$$;

