-- Phase 3: Controlled inventory movements.
-- Sales remain the responsibility of place_order().
-- Stock adjustments and audit records must be atomic.

BEGIN;

CREATE OR REPLACE FUNCTION public.record_inventory_movement(
    p_product_id integer,
    p_reason text,
    p_quantity integer,
    p_note text DEFAULT NULL,
    p_inspection_approved boolean DEFAULT FALSE
)
RETURNS TABLE (
    new_stock_quantity integer,
    inventory_log_id integer
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$

DECLARE
    v_reason text;
    v_current_stock integer;
    v_change_qty bigint;
    v_new_stock bigint;
    v_log_id integer;
    v_note text;

BEGIN

    -- 1. Validate required inputs.
    IF p_product_id IS NULL
        OR p_reason IS NULL
        OR p_quantity IS NULL THEN

        RAISE EXCEPTION
            'Product ID, movement reason and quantity are required.';
    END IF;


    -- 2. Normalize and validate the movement reason.
    v_reason := lower(trim(p_reason));

    IF v_reason NOT IN (
        'restock',
        'return',
        'correction',
        'damage',
        'stock_take'
    ) THEN

        RAISE EXCEPTION
            'Invalid inventory movement reason: %', p_reason;
    END IF;


    -- 3. Validate quantities according to the movement type.
    IF v_reason IN ('restock', 'return', 'damage')
        AND p_quantity <= 0 THEN

        RAISE EXCEPTION
            'Quantity must be positive for % movements.', v_reason;

    ELSIF v_reason = 'correction'
        AND p_quantity = 0 THEN

        RAISE EXCEPTION
            'Correction quantity cannot be zero.';

    ELSIF v_reason = 'stock_take'
        AND p_quantity < 0 THEN

        RAISE EXCEPTION
            'Physically counted stock cannot be negative.';
    END IF;


    -- 4. Returned products must pass inspection
    -- before entering sellable inventory.
    IF v_reason = 'return'
        AND p_inspection_approved IS NOT TRUE THEN

        RAISE EXCEPTION
            'Return rejected: successful inspection is required.';
    END IF;


    -- 5. Retrieve and lock the product row.
    -- Competing stock movements must wait for this lock.
    SELECT p.stock_quantity
    INTO v_current_stock
    FROM public.products AS p
    WHERE p.product_id = p_product_id
    FOR UPDATE;


    -- 6. Validate product existence and recorded stock.
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Product % does not exist.', p_product_id;
    END IF;

    IF v_current_stock IS NULL THEN
        RAISE EXCEPTION
            'Product % has an unknown stock balance.', p_product_id;
    END IF;


    -- 7. Calculate the signed inventory adjustment.
    CASE v_reason

        WHEN 'restock' THEN
            v_change_qty := p_quantity;

        WHEN 'return' THEN
            v_change_qty := p_quantity;

        WHEN 'correction' THEN
            v_change_qty := p_quantity;

        WHEN 'damage' THEN
            v_change_qty := -p_quantity::bigint;

        WHEN 'stock_take' THEN
            v_change_qty :=
                p_quantity::bigint - v_current_stock;

    END CASE;


    -- 8. Calculate and validate the resulting stock balance.
    v_new_stock := v_current_stock::bigint + v_change_qty;

    IF v_new_stock < 0 THEN
        RAISE EXCEPTION
            'Insufficient stock. Movement would result in negative stock.';
    END IF;

    -- Both stock_quantity and change_qty are integer columns.
    -- Reject values outside their supported range.
    IF v_new_stock > 2147483647
        OR v_change_qty > 2147483647
        OR v_change_qty < -2147483648 THEN

        RAISE EXCEPTION
            'Inventory movement exceeds the supported integer range.';
    END IF;


    -- 9. Build an audit note containing the stock balances.
    v_note := format(
        'Previous stock: %s; New stock: %s',
        v_current_stock,
        v_new_stock
    );

    IF v_reason = 'return' THEN
        v_note := v_note || '; Return inspection approved';
    END IF;

    IF NULLIF(trim(p_note), '') IS NOT NULL THEN
        v_note := v_note || '; Note: ' || trim(p_note);
    END IF;


    -- 10. Update the product's stock balance.
    UPDATE public.products AS p
    SET stock_quantity = v_new_stock::integer
    WHERE p.product_id = p_product_id;


    -- 11. Record the corresponding inventory movement.
    -- The existing sequence automatically generates log_id.
    INSERT INTO public.inventory_log AS il (
        product_id,
        change_qty,
        reason,
        created_at,
        note
    )
    VALUES (
        p_product_id,
        v_change_qty::integer,
        v_reason,
        CURRENT_TIMESTAMP,
        v_note
    )
    RETURNING il.log_id
    INTO v_log_id;


    -- 12. Return the resulting stock balance and audit ID.
    RETURN QUERY
    SELECT
        v_new_stock::integer,
        v_log_id;

END;

$function$;


-- Restrict execution until application permissions are configured.
REVOKE EXECUTE ON FUNCTION public.record_inventory_movement(
    integer,
    text,
    integer,
    text,
    boolean
) FROM PUBLIC;

COMMIT;