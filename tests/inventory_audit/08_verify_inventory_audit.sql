-- Phase 3: Final inventory audit verification.
-- Read-only verification of cleanup, security and integrity.

BEGIN READ ONLY;


-- 1. Check for remaining synthetic inventory test products.
SELECT COUNT(*) AS remaining_test_products
FROM public.products
WHERE product_name LIKE 'INVENTORY AUDIT TEST FIXTURE%'
    OR product_name LIKE 'INVENTORY ROLLBACK TEST FIXTURE%'
    OR product_name LIKE 'INVENTORY CONCURRENCY TEST FIXTURE%'
    OR product_name LIKE 'INVENTORY PERMISSIONS TEST FIXTURE%'
    OR product_name LIKE 'RACE TEST FIXTURE%';


-- 2. Verify historical inventory integrity findings.
SELECT
    COUNT(*) FILTER (
        WHERE stock_quantity < 0
    ) AS products_with_negative_stock,
    COUNT(*) FILTER (
        WHERE stock_quantity IS NULL
    ) AS products_with_null_stock
FROM public.products;


SELECT
    COUNT(*) FILTER (
        WHERE il.product_id IS NOT NULL
            AND p.product_id IS NULL
    ) AS logs_with_orphaned_product_id,
    COUNT(*) FILTER (
        WHERE il.product_id IS NULL
    ) AS logs_with_null_product_id
FROM public.inventory_log AS il
LEFT JOIN public.products AS p
    ON il.product_id = p.product_id;


-- 3. Verify historical movement counts.
SELECT
    reason,
    COUNT(*) AS movement_count,
    COUNT(*) FILTER (
        WHERE change_qty > 0
    ) AS increases,
    COUNT(*) FILTER (
        WHERE change_qty < 0
    ) AS decreases,
    COUNT(*) FILTER (
        WHERE change_qty = 0
    ) AS zero_changes
FROM public.inventory_log
GROUP BY reason
ORDER BY reason;


-- 4. Verify that the simulated failure constraint was removed.
SELECT COUNT(*) AS remaining_test_constraints
FROM pg_constraint
WHERE conrelid = 'public.inventory_log'::regclass
    AND conname = 'test_inventory_audit_failure';


-- 5. Verify approved function ownership and security.
SELECT
    p.proname AS function_name,
    pg_get_function_identity_arguments(p.oid) AS arguments,
    pg_get_userbyid(p.proowner) AS function_owner,
    p.prosecdef AS security_definer,
    p.proconfig AS function_settings
FROM pg_proc AS p
JOIN pg_namespace AS n
    ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.proname IN (
        'place_order',
        'record_inventory_movement'
    )
ORDER BY p.proname;


-- 6. Verify role attributes.
SELECT
    rolname,
    rolsuper,
    rolcreaterole,
    rolcreatedb,
    rolcanlogin,
    rolreplication,
    rolbypassrls
FROM pg_roles
WHERE rolname IN (
    'kloudkart_app',
    'kloudkart_function_owner'
)
ORDER BY rolname;


-- 7. Verify application execution permissions.
SELECT
    has_function_privilege(
        'kloudkart_app',
        'public.place_order(bigint,bigint,integer)',
        'EXECUTE'
    ) AS can_execute_checkout,

    has_function_privilege(
        'kloudkart_app',
        'public.record_inventory_movement(integer,text,integer,text,boolean)',
        'EXECUTE'
    ) AS can_execute_inventory_movement;


-- 8. Check for unintended direct application privileges.
-- Include column-level permissions, not just table-level grants.

SELECT
    table_name,

    has_table_privilege(
        'kloudkart_app', table_name, 'SELECT'
    ) OR has_any_column_privilege(
        'kloudkart_app', table_name, 'SELECT'
    ) AS can_select,

    has_table_privilege(
        'kloudkart_app', table_name, 'INSERT'
    ) OR has_any_column_privilege(
        'kloudkart_app', table_name, 'INSERT'
    ) AS can_insert,

    has_table_privilege(
        'kloudkart_app', table_name, 'UPDATE'
    ) OR has_any_column_privilege(
        'kloudkart_app', table_name, 'UPDATE'
    ) AS can_update,

    has_table_privilege(
        'kloudkart_app', table_name, 'DELETE'
    ) AS can_delete,

    has_table_privilege(
        'kloudkart_app', table_name, 'TRUNCATE'
    ) AS can_truncate

FROM (
    VALUES
        ('public.products'),
        ('public.inventory_log'),
        ('public.orders'),
        ('public.order_items'),
        ('public.customers')
) AS t(table_name);


-- 9. Verify application sequence permissions.
SELECT
    sequence_name,
    has_sequence_privilege(
        'kloudkart_app', sequence_name, 'USAGE'
    ) AS can_use,
    has_sequence_privilege(
        'kloudkart_app', sequence_name, 'UPDATE'
    ) AS can_update,
    has_sequence_privilege(
        'kloudkart_app', sequence_name, 'SELECT'
    ) AS can_select
FROM (
    VALUES
        ('public.orders_order_id_seq'),
        ('public.order_items_order_item_id_seq'),
        ('public.inventory_log_log_id_seq')
) AS s(sequence_name);


-- 10. Verify schema creation and role membership restrictions.
SELECT
    has_schema_privilege(
        'kloudkart_app', 'public', 'CREATE'
    ) AS app_can_create_public_objects,

    pg_has_role(
        'kloudkart_app',
        'kloudkart_function_owner',
        'MEMBER'
    ) AS app_is_function_owner_member;


-- 11. Verify that the function owner cannot alter old audit records.
SELECT
    has_table_privilege(
        'kloudkart_function_owner',
        'public.inventory_log',
        'UPDATE'
    ) OR has_any_column_privilege(
        'kloudkart_function_owner',
        'public.inventory_log',
        'UPDATE'
    ) AS owner_can_update_audit,

    has_table_privilege(
        'kloudkart_function_owner',
        'public.inventory_log',
        'DELETE'
    ) AS owner_can_delete_audit,

    has_table_privilege(
        'kloudkart_function_owner',
        'public.inventory_log',
        'TRUNCATE'
    ) AS owner_can_truncate_audit;


COMMIT;
