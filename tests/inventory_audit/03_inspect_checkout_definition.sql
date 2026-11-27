-- Phase 3: Inventory audit
-- Investigation 3: Inspect existing checkout implementation
-- and current inventory table definitions.

-- 1. Retrieve the existing checkout function definition.
SELECT pg_get_functiondef(p.oid) AS function_definition
FROM pg_proc AS p
JOIN pg_namespace AS n
    ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.proname = 'place_order';


-- 2. Inspect current inventory table columns and defaults.
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default,
    is_identity
FROM information_schema.columns
WHERE table_schema = 'public'
    AND table_name IN ('products', 'inventory_log')
ORDER BY table_name, ordinal_position;


-- 3. Inspect checkout function ownership and security settings.
SELECT
    p.proname AS function_name,
    pg_get_function_identity_arguments(p.oid) AS arguments,
    pg_get_userbyid(p.proowner) AS function_owner,
    p.prosecdef AS security_definer,
    p.proconfig AS function_settings,
    p.proacl AS function_privileges
FROM pg_proc AS p
JOIN pg_namespace AS n
    ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.proname = 'place_order';


-- 4. Inspect existing sequences used for ID generation.
SELECT
    schemaname,
    sequencename,
    data_type,
    increment_by,
    cache_size,
    cycle
FROM pg_sequences
WHERE schemaname = 'public'
ORDER BY sequencename;