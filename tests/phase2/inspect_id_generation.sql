
-- Phase 2: Safe ID generation
-- Purpose: Inspect existing primary-key values and sequences.
-- These queries are read-only.

-- Check 1: Inspect existing IDs in the three checkout tables.
SELECT
    'orders' AS table_name,
    COUNT(*) AS row_count,
    MIN(order_id) AS minimum_id,
    MAX(order_id) AS maximum_id
FROM orders

UNION ALL

SELECT
    'order_items',
    COUNT(*),
    MIN(order_item_id),
    MAX(order_item_id)
FROM order_items

UNION ALL

SELECT
    'inventory_log',
    COUNT(*),
    MIN(log_id),
    MAX(log_id)
FROM inventory_log;


-- Check 2: Inspect existing PostgreSQL sequences.
SELECT
    schemaname,
    sequencename,
    data_type,
    start_value,
    min_value,
    max_value,
    increment_by,
    last_value
FROM pg_sequences
WHERE schemaname = 'public'
ORDER BY sequencename;

-- Check 3: Inspect for orphaned order_item rows.
-- Purpose: Identify any order_item rows that reference a non-existent order.
SELECT
    COUNT(*) FILTER (
        WHERE oi.order_id IS NOT NULL
          AND o.order_id IS NULL
    ) AS orphaned_order_item_rows,

    MAX(oi.order_id) FILTER (
        WHERE oi.order_id IS NOT NULL
          AND o.order_id IS NULL
    ) AS highest_orphaned_order_id,

    MAX(oi.order_id) AS highest_order_id_referenced_by_items,

    (SELECT MAX(order_id) FROM orders)
        AS highest_existing_order_id

FROM order_items AS oi
LEFT JOIN orders AS o
    ON oi.order_id = o.order_id;