-- Investigation 6 only. The runner substitutes a fresh, quoted schema name.
-- Same checkout operations and refusal rules as functions/phase2_place_order.sql.
-- No public function replacement, indexes, configuration or timing-log tables.
-- Milliseconds use wall-clock time and include scheduler pauses and lock waits.
CREATE FUNCTION __DIAGNOSTIC_SCHEMA__.place_order_timed(
    p_customer_id bigint, p_product_id bigint, p_quantity integer
)
RETURNS TABLE (
    success boolean, order_id bigint, message text,
    stock_update_ms double precision, order_insert_ms double precision,
    order_item_insert_ms double precision, inventory_log_insert_ms double precision,
    function_ms double precision, post_update_function_ms double precision,
    stock_completed_epoch double precision, function_finished_epoch double precision
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_unit_price numeric(12,2);
    v_stock_quantity integer;
    v_new_order_id bigint;
    v_started timestamptz := clock_timestamp();
    v_stage_started timestamptz;
    v_stock_finished timestamptz;
    v_finished timestamptz;
    v_stock_found boolean;
BEGIN
    -- A labelled block allows all original outcomes to share timing/return code.
    <<checkout>>
    BEGIN
        IF p_customer_id IS NULL OR p_product_id IS NULL
           OR p_quantity IS NULL OR p_quantity <= 0 THEN
            success := FALSE; message := 'Invalid checkout input.';
            EXIT checkout;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM public.customers AS c
            WHERE c.customer_id = p_customer_id
        ) THEN
            success := FALSE; message := 'Customer not found.';
            EXIT checkout;
        END IF;

        v_stage_started := clock_timestamp();
        UPDATE public.products AS p
        SET stock_quantity = p.stock_quantity - p_quantity
        WHERE p.product_id = p_product_id
          AND p.stock_quantity >= p_quantity
          AND p.price IS NOT NULL AND p.price >= 0
        RETURNING p.price INTO v_unit_price;
        v_stock_found := FOUND;
        v_stock_finished := clock_timestamp();
        stock_update_ms := EXTRACT(EPOCH FROM (v_stock_finished - v_stage_started)) * 1000;

        IF NOT v_stock_found THEN
            SELECT p.stock_quantity, p.price
            INTO v_stock_quantity, v_unit_price
            FROM public.products AS p WHERE p.product_id = p_product_id;
            IF NOT FOUND THEN
                message := 'Product not found.';
            ELSIF v_unit_price IS NULL OR v_unit_price < 0 THEN
                message := 'Invalid product price.';
            ELSE
                message := 'Out of stock.';
            END IF;
            success := FALSE;
            EXIT checkout;
        END IF;

        v_stage_started := clock_timestamp();
        INSERT INTO public.orders AS o (customer_id, order_date, status, total_amount)
        VALUES (p_customer_id, CURRENT_TIMESTAMP, 'pending', v_unit_price * p_quantity)
        RETURNING o.order_id INTO v_new_order_id;
        order_insert_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_stage_started)) * 1000;

        v_stage_started := clock_timestamp();
        INSERT INTO public.order_items (order_id, product_id, quantity, unit_price)
        VALUES (v_new_order_id, p_product_id, p_quantity, v_unit_price);
        order_item_insert_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_stage_started)) * 1000;

        v_stage_started := clock_timestamp();
        INSERT INTO public.inventory_log (product_id, change_qty, reason, created_at, note)
        VALUES (p_product_id, -p_quantity, 'sale', CURRENT_TIMESTAMP,
                'Sale recorded for order ID ' || v_new_order_id);
        inventory_log_insert_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_stage_started)) * 1000;

        success := TRUE;
        order_id := v_new_order_id;
        message := 'Order placed successfully.';
    END checkout;

    -- This is just before result construction, NOT the transaction commit.
    v_finished := clock_timestamp();
    function_ms := EXTRACT(EPOCH FROM (v_finished - v_started)) * 1000;
    post_update_function_ms := EXTRACT(EPOCH FROM (v_finished - v_stock_finished)) * 1000;
    stock_completed_epoch := EXTRACT(EPOCH FROM v_stock_finished);
    function_finished_epoch := EXTRACT(EPOCH FROM v_finished);
    RETURN NEXT;
    RETURN;
END;
$$;
