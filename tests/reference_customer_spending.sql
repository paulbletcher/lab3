-- Retained pre-optimization summary for exact bidirectional comparison.
CREATE OR REPLACE TEMP VIEW reference_customer_spending AS

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


