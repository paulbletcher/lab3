-- Phase 4, Step 5: Calculate the verified reporting baseline.
-- Read-only investigation.

WITH completed_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.order_date,
        o.total_amount,
        c.customer_id AS matched_customer_id
    FROM orders AS o
    LEFT JOIN customers AS c
        ON o.customer_id = c.customer_id
    WHERE LOWER(BTRIM(o.status)) IN ('complete', 'completed')
)

SELECT
    CURRENT_DATE AS reporting_date,

    COUNT(*) AS all_completed_status_orders,

    COUNT(*) FILTER (
        WHERE order_date < CURRENT_DATE + INTERVAL '1 day'
    ) AS orders_within_reporting_date,

    COUNT(*) FILTER (
        WHERE order_date < CURRENT_DATE + INTERVAL '1 day'
          AND matched_customer_id IS NOT NULL
          AND total_amount IS NOT NULL
    ) AS eligible_customer_orders,

    COUNT(*) FILTER (
        WHERE order_date < CURRENT_DATE + INTERVAL '1 day'
          AND matched_customer_id IS NULL
    ) AS orphaned_customer_orders,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE order_date < CURRENT_DATE + INTERVAL '1 day'
              AND matched_customer_id IS NOT NULL
              AND total_amount IS NOT NULL
        ), 2
    ) AS eligible_customer_spending,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE order_date < CURRENT_DATE + INTERVAL '1 day'
              AND matched_customer_id IS NULL
        ), 2
    ) AS excluded_orphaned_order_value,

    COUNT(*) FILTER (
        WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
    ) AS future_dated_orders

FROM completed_orders;
