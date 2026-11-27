-- Read-only metadata; no credentials or customer rows.
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('server_version','max_connections','shared_buffers','work_mem',
 'effective_cache_size','synchronous_commit','fsync','jit','jit_above_cost',
 'max_parallel_workers_per_gather','ssl','huge_pages') ORDER BY name;
SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname='public' ORDER BY tablename,indexname;
SELECT n.nspname, c.relname, pg_get_triggerdef(t.oid)
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE NOT t.tgisinternal AND n.nspname='public';
SELECT state, wait_event_type, wait_event, count(*) FROM pg_stat_activity
WHERE datname=current_database() AND pid<>pg_backend_pid()
GROUP BY state,wait_event_type,wait_event;
EXPLAIN (FORMAT JSON) SELECT 1 FROM public.customers
WHERE customer_id=(SELECT min(customer_id)::bigint FROM public.customers);
EXPLAIN (FORMAT JSON) UPDATE public.products SET stock_quantity=stock_quantity-1
WHERE product_id=(SELECT max(product_id)::bigint+1100 FROM public.products)
AND stock_quantity>=1 AND price IS NOT NULL AND price>=0;
