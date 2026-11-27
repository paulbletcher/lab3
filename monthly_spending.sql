-- Phase 3, Step 3.4: one row per customer per reporting month.
-- Direct output is confidential. Aggregate-only verification:
-- python tests/verify_monthly_spending.py
WITH report_parameters AS (
    SELECT TIMESTAMP '2026-11-27 00:00:00' AS cutoff
),
month_anchor AS (
    -- PostgreSQL timestamps have microsecond precision; the cutoff is exclusive.
    SELECT cutoff,
           DATE_TRUNC('month', cutoff - INTERVAL '1 microsecond') AS last_month
    FROM report_parameters
),
report_window AS (
    SELECT cutoff,
           last_month - INTERVAL '11 months' AS window_start,
           last_month
    FROM month_anchor
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
),
reporting_months AS (
    SELECT m.spending_month::date AS spending_month
    FROM report_window AS rw
    CROSS JOIN LATERAL GENERATE_SERIES(
        rw.window_start, rw.last_month, INTERVAL '1 month'
    ) AS m(spending_month)
),
windowed_orders AS (
    SELECT b.order_id, b.customer_id, b.order_date, b.total_amount
    FROM report_base AS b
    CROSS JOIN report_window AS rw
    WHERE b.order_date >= rw.window_start
      AND b.order_date < rw.cutoff
),
monthly_totals AS (
    SELECT customer_id,
           DATE_TRUNC('month', order_date)::date AS spending_month,
           COALESCE(SUM(total_amount), 0) AS monthly_recorded_spending,
           COUNT(order_id) AS completed_order_count,
           COUNT(order_id) FILTER (
               WHERE total_amount IS NULL
           ) AS missing_amount_count
    FROM windowed_orders
    GROUP BY customer_id, DATE_TRUNC('month', order_date)::date
),
customer_month_grid AS (
    SELECT c.customer_id, m.spending_month
    FROM customers AS c
    CROSS JOIN reporting_months AS m
)
SELECT g.customer_id,
       g.spending_month,
       COALESCE(t.monthly_recorded_spending, 0) AS monthly_recorded_spending,
       COALESCE(t.completed_order_count, 0) AS completed_order_count,
       COALESCE(t.missing_amount_count, 0) AS missing_amount_count
FROM customer_month_grid AS g
LEFT JOIN monthly_totals AS t
    ON t.customer_id = g.customer_id
   AND t.spending_month = g.spending_month;
