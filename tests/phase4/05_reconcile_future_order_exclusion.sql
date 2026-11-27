-- Phase 4, Step 6: Reconcile future-dated completed orders.
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
    COUNT(*) FILTER (
        WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
    ) AS future_orders,

    COUNT(*) FILTER (
        WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
          AND matched_customer_id IS NOT NULL
    ) AS future_orders_with_valid_customers,

    COUNT(*) FILTER (
        WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
          AND matched_customer_id IS NULL
    ) AS future_orphaned_orders,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
        ), 2
    ) AS all_future_order_value,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
              AND matched_customer_id IS NOT NULL
        ), 2
    ) AS future_valid_customer_order_value,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE order_date >= CURRENT_DATE + INTERVAL '1 day'
              AND matched_customer_id IS NULL
        ), 2
    ) AS future_orphaned_order_value,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE matched_customer_id IS NOT NULL
        ), 2
    ) AS spending_without_date_cutoff,

    ROUND(
        SUM(total_amount) FILTER (
            WHERE matched_customer_id IS NOT NULL
              AND order_date < CURRENT_DATE + INTERVAL '1 day'
        ), 2
    ) AS spending_with_date_cutoff

FROM completed_orders;
