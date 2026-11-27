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

WITH customer_totals AS (
    SELECT
        customer_id,
        COUNT(*) AS order_count,
        SUM(order_spend) AS total_spent
    FROM public.report_eligible_completed_orders
    GROUP BY customer_id
),

month_series AS (
    SELECT generate_series(
        DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months',
        DATE_TRUNC('month', CURRENT_DATE),
        INTERVAL '1 month'
    )::date AS month_start
),

monthly_totals AS (
    SELECT
        customer_id,
        order_month,
        SUM(order_spend) AS monthly_spend
    FROM public.report_eligible_completed_orders
    WHERE order_date >=
        DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months'
    GROUP BY customer_id, order_month
),

customer_months AS (
    SELECT
        c.customer_id,
        ms.month_start,
        COALESCE(mt.monthly_spend, 0::numeric) AS monthly_spend
    FROM customers AS c
    CROSS JOIN month_series AS ms
    LEFT JOIN monthly_totals AS mt
        ON mt.customer_id = c.customer_id
       AND mt.order_month = ms.month_start
),

monthly_json AS (
    SELECT
        customer_id,
        JSONB_OBJECT_AGG(
            TO_CHAR(month_start, 'YYYY-MM'),
            monthly_spend
            ORDER BY month_start
        ) AS monthly_spend_trailing_12_months
    FROM customer_months
    GROUP BY customer_id
),

ranked_customers AS (
    SELECT
        c.customer_id,
        c.full_name,
        COALESCE(ct.order_count, 0) AS order_count,
        COALESCE(ct.total_spent, 0::numeric) AS total_spent,
        mj.monthly_spend_trailing_12_months,

        RANK() OVER (
            ORDER BY COALESCE(ct.total_spent, 0) DESC
        ) AS spending_rank,

        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(ct.total_spent, 0) DESC,
                c.customer_id
        ) AS top_100_position

    FROM customers AS c
    LEFT JOIN customer_totals AS ct
        ON ct.customer_id = c.customer_id
    LEFT JOIN monthly_json AS mj
        ON mj.customer_id = c.customer_id
)

SELECT
    customer_id,
    full_name,
    order_count,
    total_spent,
    monthly_spend_trailing_12_months,
    spending_rank,
    top_100_position,
    (top_100_position <= 100) AS is_top_100
FROM ranked_customers;


-- VALIDATION 1: Customer and spending totals.
SELECT
    COUNT(*) AS total_customers,
    COUNT(*) FILTER (
        WHERE order_count > 0
    ) AS customers_with_orders,
    COUNT(*) FILTER (
        WHERE order_count = 0
    ) AS customers_without_orders,
    SUM(order_count) AS total_orders,
    ROUND(SUM(total_spent), 2) AS total_spending,
    COUNT(*) FILTER (
        WHERE JSONB_OBJECT_LENGTH(
            monthly_spend_trailing_12_months
        ) = 12
    ) AS customers_with_12_months
FROM public.report_customer_spending;


-- VALIDATION 2: Top 10 customers.
SELECT
    customer_id,
    full_name,
    order_count,
    ROUND(total_spent, 2) AS total_spent,
    spending_rank,
    top_100_position
FROM public.report_customer_spending
WHERE is_top_100
ORDER BY top_100_position
LIMIT 10;


-- VALIDATION 3: Confirm exactly 100 top-100 positions.
SELECT
    COUNT(*) AS top_100_customers
FROM public.report_customer_spending
WHERE is_top_100;


-- VALIDATION 4: Sample running totals.
SELECT *
FROM public.report_customer_order_running_totals
ORDER BY customer_id, order_date, order_id
LIMIT 10;
