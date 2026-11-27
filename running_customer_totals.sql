-- Phase 3, Step 3.5: preserve individual eligible order rows.
-- Direct output is confidential. Aggregate-only verification:
-- python tests/verify_running_totals.py
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
),
customer_ranks AS (
    SELECT customer_id,
           RANK() OVER (
               ORDER BY total_recorded_spending DESC
           ) AS customer_total_spend_rank
    FROM customer_spending
),
order_windows AS (
    SELECT b.*,
           COALESCE(SUM(total_amount) OVER customer_rows, 0) AS running_recorded_spending,
           COUNT(order_id) FILTER (
               WHERE total_amount IS NULL
           ) OVER customer_rows AS running_missing_amount_count,
           COUNT(order_id) OVER customer_rows AS running_order_count,
           LAG(order_date) OVER customer_order AS previous_order_date,
           COALESCE(SUM(total_amount) OVER date_peers, 0) AS date_peer_recorded_spending
    FROM report_base AS b
    WINDOW customer_order AS (
               PARTITION BY customer_id ORDER BY order_date, order_id
           ),
           customer_rows AS (
               customer_order ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ),
           date_peers AS (
               PARTITION BY customer_id ORDER BY order_date
               RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           )
)
SELECT o.customer_id,
       o.order_id,
       o.order_date,
       o.total_amount,
       o.running_recorded_spending,
       o.running_missing_amount_count,
       o.running_order_count,
       o.previous_order_date,
       o.order_date::date - o.previous_order_date::date AS days_since_previous_order,
       r.customer_total_spend_rank,
       o.date_peer_recorded_spending
FROM order_windows AS o
INNER JOIN customer_ranks AS r ON r.customer_id = o.customer_id
ORDER BY o.customer_id, o.order_date, o.order_id;
