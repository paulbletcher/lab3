-- Phase 3: Inventory access control.
-- Restrict application writes to approved database functions.
-- Preserve the existing checkout and inventory movement logic.

BEGIN;


-- 1. Create dedicated roles.
-- Neither role can log in directly.

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'kloudkart_function_owner') THEN
        CREATE ROLE kloudkart_function_owner NOLOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'kloudkart_app') THEN
        CREATE ROLE kloudkart_app NOLOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT FROM pg_roles
               WHERE rolname IN ('kloudkart_function_owner', 'kloudkart_app')
                 AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                      OR rolreplication OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Existing application roles have unsafe attributes';
    END IF;
END;
$roles$;


-- 2. Allow access to objects within the public schema.
-- Application roles must not create objects in this schema.

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public
TO kloudkart_function_owner, kloudkart_app;


-- 3. Remove direct application access to operational tables.

REVOKE ALL PRIVILEGES ON TABLE
    public.products,
    public.customers,
    public.orders,
    public.order_items,
    public.inventory_log
FROM PUBLIC, kloudkart_app;


-- 4. Grant the function owner only the permissions
-- required by the existing functions.

-- Customer validation during checkout.
GRANT SELECT (customer_id)
ON public.customers
TO kloudkart_function_owner;


-- Product validation and stock adjustment.
GRANT SELECT (
    product_id,
    price,
    stock_quantity
)
ON public.products
TO kloudkart_function_owner;

GRANT UPDATE (stock_quantity)
ON public.products
TO kloudkart_function_owner;


-- Order creation.
GRANT INSERT (
    customer_id,
    order_date,
    status,
    total_amount
)
ON public.orders
TO kloudkart_function_owner;

GRANT SELECT (order_id)
ON public.orders
TO kloudkart_function_owner;


-- Order-item creation.
GRANT INSERT (
    order_id,
    product_id,
    quantity,
    unit_price
)
ON public.order_items
TO kloudkart_function_owner;


-- Inventory audit insertion.
-- No UPDATE or DELETE privileges are granted.

GRANT INSERT (
    product_id,
    change_qty,
    reason,
    created_at,
    note
)
ON public.inventory_log
TO kloudkart_function_owner;

GRANT SELECT (log_id)
ON public.inventory_log
TO kloudkart_function_owner;


-- 5. Allow automatic ID generation inside the functions.

REVOKE ALL PRIVILEGES ON SEQUENCE
    public.orders_order_id_seq,
    public.order_items_order_item_id_seq,
    public.inventory_log_log_id_seq
FROM PUBLIC, kloudkart_app;

GRANT USAGE ON SEQUENCE
    public.orders_order_id_seq,
    public.order_items_order_item_id_seq,
    public.inventory_log_log_id_seq
TO kloudkart_function_owner;


-- 6. Transfer ownership of the approved functions.
-- Existing function bodies remain unchanged.

ALTER FUNCTION public.place_order(
    bigint,
    bigint,
    integer
)
OWNER TO kloudkart_function_owner;

ALTER FUNCTION public.record_inventory_movement(
    integer,
    text,
    integer,
    text,
    boolean
)
OWNER TO kloudkart_function_owner;


-- 7. Execute functions using their owner's limited privileges.

ALTER FUNCTION public.place_order(
    bigint,
    bigint,
    integer
)
SECURITY DEFINER;

ALTER FUNCTION public.record_inventory_movement(
    integer,
    text,
    integer,
    text,
    boolean
)
SECURITY DEFINER;


-- 8. Configure a safe search path.
-- Both functions explicitly qualify operational table names.

ALTER FUNCTION public.place_order(
    bigint,
    bigint,
    integer
)
SET search_path = pg_catalog, pg_temp;

ALTER FUNCTION public.record_inventory_movement(
    integer,
    text,
    integer,
    text,
    boolean
)
SET search_path = pg_catalog, pg_temp;


-- 9. Remove unrestricted function execution.

REVOKE ALL PRIVILEGES ON FUNCTION public.place_order(
    bigint,
    bigint,
    integer
)
FROM PUBLIC;

REVOKE ALL PRIVILEGES ON FUNCTION public.record_inventory_movement(
    integer,
    text,
    integer,
    text,
    boolean
)
FROM PUBLIC;


-- 10. Allow the application role to execute approved functions.

GRANT EXECUTE ON FUNCTION public.place_order(
    bigint,
    bigint,
    integer
)
TO kloudkart_app;

GRANT EXECUTE ON FUNCTION public.record_inventory_movement(
    integer,
    text,
    integer,
    text,
    boolean
)
TO kloudkart_app;


COMMIT;