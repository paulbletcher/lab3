
-- Phase 2 Performance Investigation
-- Investigation 1: Inspect the PostgreSQL environment,
-- checkout function, indexes, triggers and database statistics.
--
-- Purpose: Identify possible sources of delay in the
-- 400-buyer flash-sale concurrency test.
--
-- All queries in this file are READ-ONLY.

-- =========================================================
-- CHECK 1: PostgreSQL server configuration
-- =========================================================

SELECT
    version() AS server_version,
    current_database() AS database_name,
    current_setting('max_connections') AS max_connections,
    current_setting('shared_buffers') AS shared_buffers,
    current_setting('work_mem') AS work_mem,
    current_setting('effective_cache_size') AS effective_cache_size,
    current_setting('synchronous_commit') AS synchronous_commit,
    current_setting('fsync') AS fsync;


-- =========================================================
-- CHECK 2: Current database connection activity
-- =========================================================

SELECT
    state,
    COUNT(*) AS connection_count
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY state
ORDER BY state;


-- =========================================================
-- CHECK 3: Inspect checkout-related table sizes
-- =========================================================

SELECT
    relname AS table_name,
    n_live_tup AS estimated_live_rows,
    n_tup_ins AS inserted_rows,
    n_tup_upd AS updated_rows,
    n_tup_del AS deleted_rows,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
WHERE relname IN (
    'products',
    'orders',
    'order_items',
    'inventory_log'
)
ORDER BY relname;


-- =========================================================
-- CHECK 4: Inspect indexes on checkout-related tables
-- =========================================================

SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN (
      'products',
      'orders',
      'order_items',
      'inventory_log'
  )
ORDER BY tablename, indexname;


-- =========================================================
-- CHECK 5: Inspect triggers on checkout-related tables
-- =========================================================

SELECT
    event_object_table AS table_name,
    trigger_name,
    action_timing,
    event_manipulation,
    action_statement
FROM information_schema.triggers
WHERE event_object_schema = 'public'
  AND event_object_table IN (
      'products',
      'orders',
      'order_items',
      'inventory_log'
  )
ORDER BY event_object_table, trigger_name;


-- =========================================================
-- CHECK 6: Retrieve the actual checkout function
-- =========================================================

SELECT
    pg_get_functiondef(
        'public.place_order(bigint,bigint,integer)'::regprocedure
    ) AS checkout_function_definition;


-- =========================================================
-- CHECK 7: Database-level activity statistics
-- =========================================================

SELECT
    datname,
    xact_commit,
    xact_rollback,
    blks_read,
    blks_hit,
    deadlocks,
    temp_files,
    temp_bytes,
    stats_reset
FROM pg_stat_database
WHERE datname = current_database();


-- =========================================================
-- CHECK 8: Check whether query-level statistics are available
-- =========================================================

SELECT
    extname,
    extversion
FROM pg_extension
WHERE extname = 'pg_stat_statements';


-- =========================================================
-- CHECK 9: Check PostgreSQL function statistics configuration
-- =========================================================

SHOW track_functions;

SELECT
    funcname,
    calls,
    total_time,
    self_time
FROM pg_stat_user_functions
WHERE schemaname = 'public'
  AND funcname = 'place_order';
