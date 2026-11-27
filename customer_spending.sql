-- Phase 3, Step 3.3: one row per existing customer, identified by customer_id.
-- Local report query: output contains individual spending; do not publish it.
-- For aggregate-only verification: python tests/verify_customer_spending.py
WITH report_parameters AS (
    SELECT TIMESTAMP '2026-11-27 00:00:00' AS cutoff
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
customer_spending AS (
    SELECT c.customer_id,
           COALESCE(SUM(b.total_amount), 0) AS total_recorded_spending,
           COUNT(b.order_id) AS completed_order_count,
           COUNT(b.order_id) FILTER (
               WHERE b.total_amount IS NULL
           ) AS missing_amount_count
    FROM customers AS c
    LEFT JOIN report_base AS b ON b.customer_id = c.customer_id
    GROUP BY c.customer_id
)
SELECT customer_id,
       total_recorded_spending,
       completed_order_count,
       missing_amount_count
FROM customer_spending;
