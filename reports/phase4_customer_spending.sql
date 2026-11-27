-- PHASE 4: MONDAY CUSTOMER-SPENDING REPORT
-- Three reusable views.
--
-- Business rules:
-- 1. Only complete/completed orders qualify.
-- 2. Customer references must exist.
-- 3. Future-dated orders are excluded.
-- 4. Stored order totals represent recorded spending.
-- 5. All customers remain in the summary, including zero-spend customers.
-- 6. Monthly spending covers the current and preceding 11 calendar months.

-- VIEW 1: Eligible order-level reporting data.
CREATE OR REPLACE VIEW public.report_eligible_completed_orders AS
SELECT
    o.order_id,
    o.customer_id,
    o.order_date,
    DATE_TRUNC('month', o.order_date)::date AS order_month,
    o.total_amount AS order_spend
FROM orders AS o
INNER JOIN customers AS c
    ON c.customer_id = o.customer_id
WHERE LOWER(BTRIM(o.status)) IN ('complete', 'completed')
  AND o.order_date < CURRENT_DATE + INTERVAL '1 day'
  AND o.total_amount IS NOT NULL;


-- VIEW 2: Running spending total for every customer's orders.
CREATE OR REPLACE VIEW public.report_customer_order_running_totals AS
SELECT
    e.customer_id,
    c.full_name,
    e.order_id,
    e.order_date,
    e.order_spend,

    LAG(e.order_date) OVER customer_order_window
        AS previous_order_date,

    SUM(e.order_spend) OVER (
        customer_order_window
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_customer_spend

FROM public.report_eligible_completed_orders AS e
INNER JOIN customers AS c
    ON c.customer_id = e.customer_id

WINDOW customer_order_window AS (
    PARTITION BY e.customer_id
    ORDER BY e.order_date, e.order_id
);


-- VIEW 3: One complete spending summary row per customer.
CREATE OR REPLACE VIEW public.report_customer_spending AS
WITH eligible_orders AS MATERIALIZED (
    SELECT * FROM public.report_eligible_completed_orders
),
customer_totals AS (
    SELECT customer_id, COUNT(*) AS order_count, SUM(order_spend) AS total_spent
    FROM eligible_orders GROUP BY customer_id
),
month_template AS (
    -- Build twelve zero-valued keys once, rather than 12 rows per customer.
    SELECT JSONB_OBJECT_AGG(TO_CHAR(month_start, 'YYYY-MM'), 0::numeric) AS months
    FROM generate_series(
        DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months',
        DATE_TRUNC('month', CURRENT_DATE), INTERVAL '1 month'
    ) AS m(month_start)
),
monthly_totals AS (
    SELECT customer_id, order_month, SUM(order_spend) AS monthly_spend
    FROM eligible_orders
    WHERE order_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months'
    GROUP BY customer_id, order_month
),
monthly_json AS (
    SELECT customer_id,
           JSONB_OBJECT_AGG(TO_CHAR(order_month, 'YYYY-MM'), monthly_spend)
               AS months
    FROM monthly_totals GROUP BY customer_id
),
ranked_customers AS (
    SELECT c.customer_id, c.full_name,
           COALESCE(ct.order_count, 0) AS order_count,
           COALESCE(ct.total_spent, 0::numeric) AS total_spent,
           mt.months || COALESCE(mj.months, '{}'::jsonb)
               AS monthly_spend_trailing_12_months,
           RANK() OVER (ORDER BY COALESCE(ct.total_spent, 0) DESC) AS spending_rank,
           ROW_NUMBER() OVER (
               ORDER BY COALESCE(ct.total_spent, 0) DESC, c.customer_id
           ) AS top_100_position
    FROM public.customers AS c
    CROSS JOIN month_template AS mt
    LEFT JOIN customer_totals AS ct USING (customer_id)
    LEFT JOIN monthly_json AS mj USING (customer_id)
)
SELECT customer_id, full_name, order_count, total_spent,
       monthly_spend_trailing_12_months, spending_rank, top_100_position,
       (top_100_position <= 100) AS is_top_100
FROM ranked_customers;
