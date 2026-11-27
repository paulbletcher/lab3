
-- Investigation 1: Inspect existing inventory movement controls.
-- Purpose:
-- Identify how stock changes and inventory movements are currently handled.
-- This investigation is strictly read-only.
-- No historical records or database objects will be modified.

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

-- 1. Confirm the database environment.
SELECT
    current_database() AS database_name,
    current_user AS database_user,
    current_setting('server_version') AS postgres_version;

-- 2. Inspect the products and inventory_log table definitions.
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('products', 'inventory_log')
ORDER BY table_name, ordinal_position;

-- 3. Inspect constraints on both tables.
SELECT
    conrelid::regclass AS table_name,
    conname AS constraint_name,
    contype AS constraint_type,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN (
    'public.products'::regclass,
    'public.inventory_log'::regclass
)
ORDER BY table_name, constraint_name;

-- 4. Inspect indexes on both tables.
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('products', 'inventory_log')
ORDER BY tablename, indexname;

-- 5. Check whether triggers automatically audit stock changes.
SELECT
    event_object_table AS table_name,
    trigger_name,
    event_manipulation,
    action_timing,
    action_statement
FROM information_schema.triggers
WHERE event_object_schema = 'public'
  AND event_object_table IN ('products', 'inventory_log')
ORDER BY event_object_table, trigger_name;

-- 6. Find database routines that reference stock quantities
-- or inventory movement records.
SELECT
    p.proname AS routine_name,
    pg_get_function_identity_arguments(p.oid) AS arguments,
    p.prokind AS routine_type,
    pg_get_functiondef(p.oid) AS definition
FROM pg_proc AS p
JOIN pg_namespace AS n
    ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.prokind IN ('f', 'p')
  AND (
      pg_get_functiondef(p.oid) ILIKE '%stock_quantity%'
      OR pg_get_functiondef(p.oid) ILIKE '%inventory_log%'
  )
ORDER BY p.proname;

-- 7. Re-examine inventory movement conventions.
-- Also identify missing notes, timestamps and orphaned product references.
SELECT
    COALESCE(l.reason, '<NULL>') AS movement_reason,
    COUNT(*) AS total_movements,

    COUNT(*) FILTER (
        WHERE l.change_qty > 0
    ) AS stock_increases,

    COUNT(*) FILTER (
        WHERE l.change_qty < 0
    ) AS stock_decreases,

    COUNT(*) FILTER (
        WHERE l.change_qty = 0
    ) AS zero_movements,

    COUNT(*) FILTER (
        WHERE l.change_qty IS NULL
    ) AS null_quantities,

    COUNT(*) FILTER (
        WHERE l.created_at IS NULL
    ) AS missing_timestamps,

    COUNT(*) FILTER (
        WHERE l.note IS NULL
    ) AS missing_notes,

    COUNT(*) FILTER (
        WHERE l.product_id IS NOT NULL
          AND p.product_id IS NULL
    ) AS orphaned_product_references

FROM public.inventory_log AS l
LEFT JOIN public.products AS p
    ON p.product_id = l.product_id
GROUP BY l.reason
ORDER BY l.reason NULLS FIRST;

COMMIT;
