-- Phase 3, Step 3.7: four result sets at their natural reporting grains.
-- Confidential output: do not publish or redirect individual report rows to logs.
-- Aggregate-only verification: python tests/verify_monday_spending_report.py
-- Final policy: RANK <= 100, preserving all qualifying spending ties.
\set ON_ERROR_STOP on
\pset null '[NULL]'
\set reporting_cutoff '2026-11-27 00:00:00'

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '60s';

-- Result set 1: Customer lifetime summary
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
ranked_customers AS (
    SELECT customer_id,
           total_recorded_spending,
           completed_order_count,
           missing_amount_count,
           RANK() OVER (
               ORDER BY total_recorded_spending DESC
           ) AS customer_total_spend_rank
    FROM customer_spending
)
SELECT customer_id,
       total_recorded_spending,
       completed_order_count,
       missing_amount_count,
       customer_total_spend_rank
FROM ranked_customers
ORDER BY customer_id;

-- Result set 2: Top-100 customers with ties
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
ranked_customers AS (
    SELECT customer_id,
           total_recorded_spending,
           completed_order_count,
           missing_amount_count,
           RANK() OVER (
               ORDER BY total_recorded_spending DESC
           ) AS customer_total_spend_rank
    FROM customer_spending
)
SELECT customer_id,
       total_recorded_spending,
       completed_order_count,
       customer_total_spend_rank
FROM ranked_customers
WHERE customer_total_spend_rank <= 100
ORDER BY customer_total_spend_rank, customer_id;

-- Result set 3: Trailing 12-month customer spending
WITH report_parameters AS (
    SELECT TIMESTAMP :'reporting_cutoff' AS cutoff
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
   AND t.spending_month = g.spending_month
ORDER BY g.customer_id, g.spending_month;

-- Result set 4: Lifetime order-level running totals
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
SELECT customer_id,
       order_id,
       order_date,
       total_amount,
       running_recorded_spending,
       running_missing_amount_count,
       running_order_count,
       previous_order_date,
       order_date::date - previous_order_date::date AS days_since_previous_order
FROM order_windows
ORDER BY customer_id, order_date, order_id;

COMMIT;
