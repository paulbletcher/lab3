-- Verify PostgreSQL version and connection capacity.
SHOW server_version;
SHOW max_connections;

-- Verify the number of records loaded into each table.
SELECT 'categories' AS table_name, COUNT(*) AS row_count
FROM categories

UNION ALL

SELECT 'customers', COUNT(*)
FROM customers

UNION ALL

SELECT 'products', COUNT(*)
FROM products

UNION ALL

SELECT 'orders', COUNT(*)
FROM orders

UNION ALL

SELECT 'order_items', COUNT(*)
FROM order_items

UNION ALL

SELECT 'inventory_log', COUNT(*)
FROM inventory_log;


--due to fact that i rebuilt the db
-- Check for custom functions and procedures.
SELECT
    routine_name,
    routine_type
FROM information_schema.routines
WHERE routine_schema = 'public';

-- Check for custom triggers.
SELECT
    event_object_table,
    trigger_name,
    event_manipulation
FROM information_schema.triggers
WHERE trigger_schema = 'public';

-- Check for existing views.
SELECT
    table_name
FROM information_schema.views
WHERE table_schema = 'public';

-- Check for existing sequences.
SELECT
    sequence_name
FROM information_schema.sequences
WHERE sequence_schema = 'public';

-- Check for existing indexes.
SELECT
    tablename,
    indexname
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;