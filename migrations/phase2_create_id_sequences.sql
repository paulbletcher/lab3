
-- Phase 2: Automatic ID generation
-- Purpose: Create independent sequences for checkout-related tables.
-- Existing primary-key values and historical records must remain unchanged.

BEGIN;

-- 1. Create three independent sequences.
CREATE SEQUENCE IF NOT EXISTS public.orders_order_id_seq AS integer;

CREATE SEQUENCE IF NOT EXISTS public.order_items_order_item_id_seq AS integer;

CREATE SEQUENCE IF NOT EXISTS public.inventory_log_log_id_seq AS integer;


-- 2. Attach sequences as automatic ID defaults.
ALTER TABLE public.orders
    ALTER COLUMN order_id
    SET DEFAULT nextval('public.orders_order_id_seq'::regclass);

ALTER TABLE public.order_items
    ALTER COLUMN order_item_id
    SET DEFAULT nextval('public.order_items_order_item_id_seq'::regclass);

ALTER TABLE public.inventory_log
    ALTER COLUMN log_id
    SET DEFAULT nextval('public.inventory_log_log_id_seq'::regclass);


-- 3. Associate each sequence with its respective primary-key column.
ALTER SEQUENCE public.orders_order_id_seq
    OWNED BY public.orders.order_id;

ALTER SEQUENCE public.order_items_order_item_id_seq
    OWNED BY public.order_items.order_item_id;

ALTER SEQUENCE public.inventory_log_log_id_seq
    OWNED BY public.inventory_log.log_id;


-- 4. Synchronize sequences with existing IDs without moving used sequences backwards.
-- Install during a maintenance window, with application writers stopped.
-- Orders must also account for orphaned order references in order_items.

WITH existing_ids AS (
    SELECT GREATEST(
        COALESCE((SELECT MAX(order_id)::bigint FROM public.orders), 0),
        COALESCE((SELECT MAX(order_id)::bigint FROM public.order_items), 0)
    ) AS highest_used_id
)
SELECT setval(
    'public.orders_order_id_seq'::regclass,
    GREATEST(highest_used_id, (SELECT last_value FROM public.orders_order_id_seq), 1),
    highest_used_id >= 1 OR (SELECT is_called FROM public.orders_order_id_seq)
)
FROM existing_ids;


WITH existing_ids AS (
    SELECT COALESCE(MAX(order_item_id)::bigint, 0) AS highest_used_id
    FROM public.order_items
)
SELECT setval(
    'public.order_items_order_item_id_seq'::regclass,
    GREATEST(highest_used_id, (SELECT last_value FROM public.order_items_order_item_id_seq), 1),
    highest_used_id >= 1 OR (SELECT is_called FROM public.order_items_order_item_id_seq)
)
FROM existing_ids;


WITH existing_ids AS (
    SELECT COALESCE(MAX(log_id)::bigint, 0) AS highest_used_id
    FROM public.inventory_log
)
SELECT setval(
    'public.inventory_log_log_id_seq'::regclass,
    GREATEST(highest_used_id, (SELECT last_value FROM public.inventory_log_log_id_seq), 1),
    highest_used_id >= 1 OR (SELECT is_called FROM public.inventory_log_log_id_seq)
)
FROM existing_ids;


-- 5. Verify sequence ownership and synchronization.
SELECT
    'orders' AS table_name,
    pg_get_serial_sequence('public.orders', 'order_id') AS sequence_name,
    last_value,
    is_called
FROM public.orders_order_id_seq

UNION ALL

SELECT
    'order_items',
    pg_get_serial_sequence('public.order_items', 'order_item_id'),
    last_value,
    is_called
FROM public.order_items_order_item_id_seq

UNION ALL

SELECT
    'inventory_log',
    pg_get_serial_sequence('public.inventory_log', 'log_id'),
    last_value,
    is_called
FROM public.inventory_log_log_id_seq;

COMMIT;
