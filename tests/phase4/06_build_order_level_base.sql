-- Phase 4, Step 7: Build the eligible order-level foundation.
-- Read-only query.
--
-- One row represents one eligible completed order.
-- Only valid customer references are included.

WITH report_parameters AS (
    SELECT
        CURRENT_DATE AS reporting_date,
        (
            DATE_TRUNC('month', CURRENT_DATE)
            - INTERVAL '11 months'
        )::date AS monthly_window_start
),

eligible_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.order_date,
        o.total_amount AS order_spend,
        DATE_TRUNC('month', o.order_date)::date AS order_month
    FROM orders AS o
    INNER JOIN customers AS c
        ON o.customer_id = c.customer_id
    CROSS JOIN report_parameters AS rp
    WHERE LOWER(BTRIM(o.status)) IN ('complete', 'completed')
      AND o.order_date < rp.reporting_date + INTERVAL '1 day'
      AND o.total_amount IS NOT NULL
)

SELECT
    COUNT(*) AS eligible_order_rows,

    COUNT(DISTINCT order_id) AS distinct_orders,

    COUNT(DISTINCT customer_id) AS customers_with_orders,

    ROUND(SUM(order_spend), 2) AS lifetime_recorded_spending,

    COUNT(*) FILTER (
        WHERE order_date >= rp.monthly_window_start
    ) AS orders_in_monthly_window,

    ROUND(
        SUM(order_spend) FILTER (
            WHERE order_date >= rp.monthly_window_start
        ), 2
    ) AS trailing_12_calendar_month_spending,

    MIN(order_date) AS earliest_eligible_order,

    MAX(order_date) AS latest_eligible_order,

    rp.monthly_window_start,

    rp.reporting_date

FROM eligible_orders
CROSS JOIN report_parameters AS rp
GROUP BY
    rp.monthly_window_start,
    rp.reporting_date;
