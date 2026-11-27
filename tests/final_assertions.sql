-- Non-destructive installation checks; no confidential detail rows are printed.
\ir test_support.sql
SELECT pg_temp.check(
    to_regprocedure('public.place_order(bigint,bigint,integer)') IS NOT NULL
    AND to_regprocedure('public.record_inventory_movement(integer,text,integer,text,boolean)') IS NOT NULL
    AND to_regclass('public.report_order_review_queue') IS NOT NULL,
    'checkout, movement function and improvement exist');
SELECT pg_temp.check(COUNT(*) = (SELECT COUNT(*) FROM public.customers)
    AND COUNT(*) FILTER (WHERE is_top_100) = LEAST(100, COUNT(*))
    AND SUM(order_count) = (SELECT COUNT(*) FROM public.report_eligible_completed_orders)
    AND SUM(total_spent) = (SELECT SUM(order_spend) FROM public.report_eligible_completed_orders),
    'customer coverage, top 100, order count and spending reconcile')
FROM public.report_customer_spending;
SELECT pg_temp.check(
    (SELECT COALESCE(SUM(descendant_low_stock_products),0)
     FROM public.report_low_stock_by_category WHERE parent_id IS NULL)
    = (SELECT COUNT(DISTINCT p.product_id) FROM public.products p
       JOIN public.report_category_hierarchy h USING (category_id)
       WHERE NOT h.is_cycle AND p.stock_quantity <= 10),
    'root rollup reconciles to reachable low-stock products');
SELECT pg_temp.check(COUNT(*) = 2 AND BOOL_AND(prosecdef)
    AND BOOL_AND(proconfig @> ARRAY['search_path=pg_catalog, pg_temp'])
    AND BOOL_AND(pg_get_userbyid(proowner) = 'kloudkart_function_owner'),
    'both write functions have restricted execution context')
FROM pg_proc WHERE oid IN (
    'public.place_order(bigint,bigint,integer)'::regprocedure,
    'public.record_inventory_movement(integer,text,integer,text,boolean)'::regprocedure);
SELECT pg_temp.check(NOT has_table_privilege('kloudkart_app','public.products','UPDATE')
    AND NOT has_table_privilege('kloudkart_app','public.inventory_log','INSERT,UPDATE,DELETE')
    AND has_function_privilege('kloudkart_app','public.place_order(bigint,bigint,integer)','EXECUTE'),
    'application uses approved write functions');
