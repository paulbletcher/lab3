-- PHASE 6: REPORT PERFORMANCE BASELINE
-- Capture three executions of each complete reporting view.
-- No indexes or planner settings are changed.

\pset pager off
\timing on

\echo
\echo ===== ENVIRONMENT =====

SELECT
    version() AS postgres_version,
    current_database() AS database_name,
    current_setting('max_connections') AS max_connections;

SELECT
    'customers' AS table_name, COUNT(*) AS rows FROM customers
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL
SELECT 'products', COUNT(*) FROM products
UNION ALL
SELECT 'categories', COUNT(*) FROM categories;

\echo
\echo ===== MONDAY REPORT: RUN 1 =====

EXPLAIN (ANALYZE, BUFFERS, SUMMARY)
SELECT *
FROM public.report_customer_spending;

\echo
\echo ===== MONDAY REPORT: RUN 2 =====

EXPLAIN (ANALYZE, BUFFERS, SUMMARY)
SELECT *
FROM public.report_customer_spending;

\echo
\echo ===== MONDAY REPORT: RUN 3 =====

EXPLAIN (ANALYZE, BUFFERS, SUMMARY)
SELECT *
FROM public.report_customer_spending;

\echo
\echo ===== LOW-STOCK REPORT: RUN 1 =====

EXPLAIN (ANALYZE, BUFFERS, SUMMARY)
SELECT *
FROM public.report_low_stock_by_category;

\echo
\echo ===== LOW-STOCK REPORT: RUN 2 =====

EXPLAIN (ANALYZE, BUFFERS, SUMMARY)
SELECT *
FROM public.report_low_stock_by_category;

\echo
\echo ===== LOW-STOCK REPORT: RUN 3 =====

EXPLAIN (ANALYZE, BUFFERS, SUMMARY)
SELECT *
FROM public.report_low_stock_by_category;
