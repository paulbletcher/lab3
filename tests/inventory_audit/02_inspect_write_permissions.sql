
-- Investigation 2: Inspect inventory write permissions.
-- Read-only investigation.
-- No permissions or database objects are modified.

-- 1. Inspect table ownership and access-control lists.
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    pg_get_userbyid(c.relowner) AS table_owner,
    c.relacl AS access_control_list
FROM pg_class AS c
JOIN pg_namespace AS n
    ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('products', 'inventory_log')
ORDER BY c.relname;


-- 2. Inspect explicitly granted table privileges.
SELECT
    table_name,
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name IN ('products', 'inventory_log')
ORDER BY table_name, grantee, privilege_type;


-- 3. Inspect login roles and superuser privileges.
SELECT
    rolname,
    rolsuper,
    rolcreaterole,
    rolcreatedb,
    rolcanlogin
FROM pg_roles
WHERE rolcanlogin = TRUE
   OR rolsuper = TRUE
ORDER BY rolname;


-- 4. Inspect effective permissions for login roles.
SELECT
    r.rolname AS role_name,

    has_table_privilege(
        r.rolname,
        'public.products',
        'UPDATE'
    ) AS can_update_products,

    has_table_privilege(
        r.rolname,
        'public.inventory_log',
        'INSERT'
    ) AS can_insert_inventory_logs,

    has_table_privilege(
        r.rolname,
        'public.inventory_log',
        'UPDATE'
    ) AS can_update_inventory_logs,

    has_table_privilege(
        r.rolname,
        'public.inventory_log',
        'DELETE'
    ) AS can_delete_inventory_logs

FROM pg_roles AS r
WHERE r.rolcanlogin = TRUE
   OR r.rolsuper = TRUE
ORDER BY r.rolname;
