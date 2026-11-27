-- Read-only count/orphan checks; used between tests, never during timed work.
SELECT 'customers' AS table_name,count(*) FROM public.customers
UNION ALL SELECT 'categories',count(*) FROM public.categories
UNION ALL SELECT 'products',count(*) FROM public.products
UNION ALL SELECT 'orders',count(*) FROM public.orders
UNION ALL SELECT 'order_items',count(*) FROM public.order_items
UNION ALL SELECT 'inventory_log',count(*) FROM public.inventory_log ORDER BY 1;
SELECT count(*) AS remaining_fixtures FROM public.products
WHERE product_name LIKE 'RACE TEST FIXTURE%';
SELECT
 (SELECT count(*) FROM public.orders o WHERE o.customer_id IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM public.customers c WHERE c.customer_id=o.customer_id)) AS orphan_orders_customer,
 (SELECT count(*) FROM public.order_items i WHERE i.order_id IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM public.orders o WHERE o.order_id=i.order_id)) AS orphan_items_order,
 (SELECT count(*) FROM public.order_items i WHERE i.product_id IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.product_id=i.product_id)) AS orphan_items_product,
 (SELECT count(*) FROM public.inventory_log l WHERE l.product_id IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.product_id=l.product_id)) AS orphan_logs_product;
-- Full historical fingerprints used only at start/end. The runner substitutes
-- these fixed, whitelisted identifiers for each of the six public tables:
-- SELECT count(*), md5(string_agg(md5(to_jsonb(t)::text),'' ORDER BY primary_key))
-- FROM public.table_name t;
-- Check the entire fixture ID range the original harness might use:
-- SELECT count(*) FROM public.order_items/public.inventory_log
-- WHERE product_id BETWEEN max_existing_product_id+1000 AND max_existing_product_id+1300;
