CREATE OR REPLACE FUNCTION public.place_order(p_customer_id bigint, p_product_id bigint, p_quantity integer)
 RETURNS TABLE(success boolean, order_id bigint, message text)
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_stock_quantity integer;
    v_unit_price numeric(12,2);
    v_new_order_id bigint;
BEGIN
    IF p_customer_id IS NULL OR p_product_id IS NULL
       OR p_quantity IS NULL OR p_quantity <= 0 THEN
        RETURN QUERY SELECT FALSE,NULL::bigint,'Invalid checkout input.'::text;
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.customers c WHERE c.customer_id=p_customer_id) THEN
        RETURN QUERY SELECT FALSE,NULL::bigint,'Customer not found.'::text;
        RETURN;
    END IF;

    -- Avoid planner-time casts to the integer product columns for missing
    -- bigint IDs outside the real primary-key domain; preserve customer priority.
    IF p_product_id < -2147483648 OR p_product_id > 2147483647 THEN
        RETURN QUERY SELECT FALSE,NULL::bigint,'Product not found.'::text;
        RETURN;
    END IF;

    WITH deducted AS (
        UPDATE public.products p
        SET stock_quantity=p.stock_quantity-p_quantity
        WHERE p.product_id=p_product_id AND p.stock_quantity>=p_quantity
          AND p.price IS NOT NULL AND p.price>=0
        RETURNING p.price
    ), new_order AS (
        INSERT INTO public.orders AS o(customer_id,order_date,status,total_amount)
        SELECT p_customer_id,CURRENT_TIMESTAMP,'pending',d.price*p_quantity
        FROM deducted d
        RETURNING o.order_id
    ), new_item AS (
        INSERT INTO public.order_items AS oi(order_id,product_id,quantity,unit_price)
        SELECT o.order_id,p_product_id,p_quantity,d.price
        FROM new_order o CROSS JOIN deducted d
        RETURNING oi.order_id
    ), movement AS (
        INSERT INTO public.inventory_log AS il(product_id,change_qty,reason,created_at,note)
        SELECT p_product_id,-p_quantity,'sale',CURRENT_TIMESTAMP,
               'Sale recorded for order ID '||i.order_id
        FROM new_item i
        RETURNING il.log_id
    )
    SELECT o.order_id INTO v_new_order_id
    FROM new_order o CROSS JOIN movement m;

    IF NOT FOUND THEN
        SELECT p.stock_quantity,p.price INTO v_stock_quantity,v_unit_price
        FROM public.products p WHERE p.product_id=p_product_id;
        IF NOT FOUND THEN
            RETURN QUERY SELECT FALSE,NULL::bigint,'Product not found.'::text;
        ELSIF v_unit_price IS NULL OR v_unit_price<0 THEN
            RETURN QUERY SELECT FALSE,NULL::bigint,'Invalid product price.'::text;
        ELSE
            RETURN QUERY SELECT FALSE,NULL::bigint,'Out of stock.'::text;
        END IF;
        RETURN;
    END IF;
    RETURN QUERY SELECT TRUE,v_new_order_id,'Order placed successfully.'::text;
    RETURN;
END;
$function$
