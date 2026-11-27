-- Phase 3, Step 3.2: order-level reporting base and aggregate verification only.
\set ON_ERROR_STOP on
\pset null '[NULL]'

-- Exclusive cutoff, centralized here for reproducible initial development.
\set reporting_cutoff '2026-11-27 00:00:00'

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '60s';

SELECT current_database() AS database_name,
       current_user AS database_user,
       system_identifier AS cluster_identifier,
       current_setting('transaction_isolation') AS transaction_isolation,
       current_setting('transaction_read_only') AS transaction_read_only,
       TIMESTAMP :'reporting_cutoff' AS exclusive_cutoff
FROM pg_control_system();

-- Query 1: construct the four-column base without printing individual orders.
WITH report_parameters AS (
    SELECT TIMESTAMP :'reporting_cutoff' AS cutoff
),
report_base AS (
    SELECT o.order_id,
           o.customer_id,
           o.order_date,
           o.total_amount
    FROM orders AS o
    INNER JOIN customers AS c ON c.customer_id = o.customer_id
    CROSS JOIN report_parameters AS rp
    WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed')
      AND o.order_date < rp.cutoff
)
SELECT COUNT(*) AS eligible_orders,
       COUNT(DISTINCT customer_id) AS purchasing_customers,
       COALESCE(SUM(total_amount), 0) AS recorded_spending_known_amounts,
       COUNT(total_amount) AS orders_with_known_amounts,
       COUNT(*) FILTER (WHERE total_amount IS NULL) AS orders_with_null_amounts,
       COUNT(*) FILTER (WHERE total_amount = 0) AS orders_with_zero_amounts,
       COUNT(*) FILTER (WHERE total_amount < 0) AS orders_with_negative_amounts,
       MIN(order_date) AS earliest_eligible_order,
       MAX(order_date) AS latest_eligible_order,
       COUNT(*) - COUNT(DISTINCT order_id) AS duplicate_order_id_rows
FROM report_base;

-- Query 2: partition ALL normalized completed orders, including exclusions.
-- CASE priority makes these four groups mutually exclusive.
WITH report_parameters AS (
    SELECT TIMESTAMP :'reporting_cutoff' AS cutoff
),
completed_orders AS (
    SELECT o.order_id, o.customer_id, o.order_date, o.total_amount
    FROM orders AS o
    WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed')
),
classified_orders AS (
    SELECT o.order_id,
           o.total_amount,
           CASE
               WHEN o.order_date IS NULL THEN 1
               WHEN o.order_date >= rp.cutoff THEN 2
               WHEN c.customer_id IS NULL THEN 3
               ELSE 4
           END AS group_id
    FROM completed_orders AS o
    LEFT JOIN customers AS c ON c.customer_id = o.customer_id
    CROSS JOIN report_parameters AS rp
),
report_groups (group_id, group_name) AS (
    VALUES
        (1, 'Completed: missing order date'),
        (2, 'Completed: at or beyond cutoff'),
        (3, 'Completed: before cutoff, missing customer'),
        (4, 'Eligible: before cutoff, matching customer')
),
group_summary AS (
    SELECT g.group_id,
           g.group_name,
           COUNT(o.order_id) AS order_count,
           COUNT(o.total_amount) AS known_amount_count,
           COUNT(o.order_id) FILTER (WHERE o.total_amount IS NULL) AS null_amount_count,
           COALESCE(SUM(o.total_amount), 0) AS recorded_spending_known_amounts
    FROM report_groups AS g
    LEFT JOIN classified_orders AS o ON o.group_id = g.group_id
    GROUP BY g.group_id, g.group_name
)
SELECT group_id, group_name, order_count, known_amount_count,
       null_amount_count, recorded_spending_known_amounts
FROM group_summary
UNION ALL
SELECT 5, 'TOTAL: all normalized completed orders', COUNT(*), COUNT(total_amount),
       COUNT(*) FILTER (WHERE total_amount IS NULL), COALESCE(SUM(total_amount), 0)
FROM completed_orders
ORDER BY group_id;

-- Query 3: independent source/base totals versus the classified group totals.
-- Repeated CTEs keep all queries standalone; the cutoff still has one definition.
WITH report_parameters AS (
    SELECT TIMESTAMP :'reporting_cutoff' AS cutoff
),
completed_orders AS (
    SELECT o.order_id, o.customer_id, o.order_date, o.total_amount
    FROM orders AS o
    WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed')
),
report_base AS (
    SELECT o.order_id, o.customer_id, o.order_date, o.total_amount
    FROM completed_orders AS o
    INNER JOIN customers AS c ON c.customer_id = o.customer_id
    CROSS JOIN report_parameters AS rp
    WHERE o.order_date < rp.cutoff
),
classified_orders AS (
    SELECT o.order_id,
           o.total_amount,
           CASE
               WHEN o.order_date IS NULL THEN 1
               WHEN o.order_date >= rp.cutoff THEN 2
               WHEN c.customer_id IS NULL THEN 3
               ELSE 4
           END AS group_id
    FROM completed_orders AS o
    LEFT JOIN customers AS c ON c.customer_id = o.customer_id
    CROSS JOIN report_parameters AS rp
),
group_totals AS (
    SELECT group_id,
           COUNT(*) AS order_count,
           COUNT(total_amount) AS known_amount_count,
           COUNT(*) FILTER (WHERE total_amount IS NULL) AS null_amount_count,
           COALESCE(SUM(total_amount), 0) AS recorded_spending
    FROM classified_orders
    GROUP BY group_id
),
reconciled AS (
    SELECT COALESCE(SUM(order_count), 0) AS order_count,
           COALESCE(SUM(known_amount_count), 0) AS known_amount_count,
           COALESCE(SUM(null_amount_count), 0) AS null_amount_count,
           COALESCE(SUM(recorded_spending), 0) AS recorded_spending,
           COALESCE(SUM(order_count) FILTER (WHERE group_id = 4), 0) AS eligible_orders,
           COALESCE(SUM(null_amount_count) FILTER (WHERE group_id = 4), 0) AS eligible_nulls,
           COALESCE(SUM(recorded_spending) FILTER (WHERE group_id = 4), 0) AS eligible_spending
    FROM group_totals
),
source_totals AS (
    SELECT COUNT(*) AS order_count,
           COUNT(total_amount) AS known_amount_count,
           COUNT(*) FILTER (WHERE total_amount IS NULL) AS null_amount_count,
           COALESCE(SUM(total_amount), 0) AS recorded_spending
    FROM completed_orders
),
base_totals AS (
    SELECT COUNT(*) AS order_count,
           COUNT(*) FILTER (WHERE total_amount IS NULL) AS null_amount_count,
           COALESCE(SUM(total_amount), 0) AS recorded_spending,
           COUNT(*) = COUNT(DISTINCT order_id) AS unique_order_ids,
           COUNT(*) FILTER (WHERE order_date IS NULL OR order_date >= rp.cutoff) = 0 AS valid_dates
    FROM report_base
    CROSS JOIN report_parameters AS rp
),
checks AS (
    SELECT s.order_count = r.order_count AS counts_ok,
           s.recorded_spending = r.recorded_spending AS money_ok,
           s.null_amount_count = r.null_amount_count AS nulls_ok,
           s.known_amount_count = r.known_amount_count
               AND s.order_count = s.known_amount_count + s.null_amount_count AS amount_counts_ok,
           b.order_count = r.eligible_orders AS base_count_ok,
           b.recorded_spending = r.eligible_spending AS base_money_ok,
           b.null_amount_count = r.eligible_nulls AS base_nulls_ok,
           b.unique_order_ids AS unique_ids_ok,
           b.valid_dates AS dates_ok
    FROM source_totals AS s
    CROSS JOIN reconciled AS r
    CROSS JOIN base_totals AS b
)
SELECT CASE WHEN counts_ok THEN 'PASS' ELSE 'FAIL' END AS counts,
       CASE WHEN money_ok THEN 'PASS' ELSE 'FAIL' END AS money,
       CASE WHEN nulls_ok THEN 'PASS' ELSE 'FAIL' END AS nulls,
       CASE WHEN amount_counts_ok THEN 'PASS' ELSE 'FAIL' END AS amount_counts,
       CASE WHEN base_count_ok THEN 'PASS' ELSE 'FAIL' END AS base_count,
       CASE WHEN base_money_ok THEN 'PASS' ELSE 'FAIL' END AS base_money,
       CASE WHEN base_nulls_ok THEN 'PASS' ELSE 'FAIL' END AS base_nulls,
       CASE WHEN unique_ids_ok THEN 'PASS' ELSE 'FAIL' END AS unique_ids,
       CASE WHEN dates_ok THEN 'PASS' ELSE 'FAIL' END AS dates,
       counts_ok AND money_ok AND nulls_ok AND amount_counts_ok
           AND base_count_ok AND base_money_ok AND base_nulls_ok
           AND unique_ids_ok AND dates_ok AS all_ok
FROM checks
\gset validation_

\echo Completed-order count reconciliation: :validation_counts
\echo Known-amount monetary reconciliation: :validation_money
\echo NULL-amount count reconciliation: :validation_nulls
\echo Known-plus-NULL amount coverage: :validation_amount_counts
\echo Eligible-group versus base order count: :validation_base_count
\echo Eligible-group versus base spending: :validation_base_money
\echo Eligible-group versus base NULL amounts: :validation_base_nulls
\echo Unique order IDs in the base: :validation_unique_ids
\echo Base dates strictly before cutoff: :validation_dates

\if :validation_all_ok
    \echo Overall reporting-base validation: PASS
\else
    \echo Overall reporting-base validation: FAIL
    \quit 1
\endif

COMMIT;
