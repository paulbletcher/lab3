-- Phase 0: Verify the isolated development database.
-- Read-only environment inspection.

-- 1. Database identity and configuration.
SELECT
    current_database() AS database_name,
    current_user AS database_user,
    current_setting('server_version') AS postgres_version,
    current_setting('max_connections') AS max_connections;

-- 2. Verify all six original tables and their row counts.
SELECT 'categories' AS table_name, COUNT(*) AS row_count FROM categories
UNION ALL
SELECT 'products', COUNT(*) FROM products
UNION ALL
SELECT 'customers', COUNT(*) FROM customers
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL
SELECT 'inventory_log', COUNT(*) FROM inventory_log
ORDER BY table_name;

-- 3. Identify existing user-defined routines.
SELECT
    n.nspname AS schema_name,
    p.proname AS routine_name,
    p.prokind AS routine_type,
    pg_get_function_identity_arguments(p.oid) AS arguments
FROM pg_proc AS p
JOIN pg_namespace AS n
    ON p.pronamespace = n.oid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND p.prokind IN ('f', 'p')
ORDER BY n.nspname, p.proname;

-- 4. Identify non-primary-key indexes.
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname NOT LIKE '%_pkey'
ORDER BY tablename, indexname;

-- 5. Identify user-defined triggers.
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    t.tgname AS trigger_name,
    pg_get_triggerdef(t.oid) AS trigger_definition
FROM pg_trigger AS t
JOIN pg_class AS c
    ON c.oid = t.tgrelid
JOIN pg_namespace AS n
    ON n.oid = c.relnamespace
WHERE NOT t.tgisinternal
  AND n.nspname = 'public'
ORDER BY c.relname, t.tgname;
