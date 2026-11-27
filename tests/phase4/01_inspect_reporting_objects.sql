-- Phase 4: Inspect existing reporting objects.
-- Read-only investigation before reporting implementation.

-- 1. Existing ordinary views.
SELECT
    schemaname,
    viewname,
    definition
FROM pg_views
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, viewname;

-- 2. Existing materialized views.
SELECT
    schemaname,
    matviewname,
    ispopulated,
    definition
FROM pg_matviews
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, matviewname;

-- 3. Existing user-defined functions and procedures.
SELECT
    n.nspname AS schema_name,
    p.proname AS routine_name,
    pg_get_function_identity_arguments(p.oid) AS arguments,
    pg_get_function_result(p.oid) AS return_type
FROM pg_proc AS p
JOIN pg_namespace AS n
    ON p.pronamespace = n.oid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND p.prokind IN ('f', 'p')
ORDER BY schema_name, routine_name;

-- 4. Existing indexes.
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
