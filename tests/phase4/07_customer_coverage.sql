-- Phase 4, Step 8: Verify customer coverage.
-- Read-only investigation.

WITH eligible_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.total_amount
    FROM orders AS o
    INNER JOIN customers AS c
        ON o.customer_id = c.customer_id
    WHERE LOWER(BTRIM(o.status)) IN ('complete', 'completed')
      AND o.order_date < CURRENT_DATE + INTERVAL '1 day'
      AND o.total_amount IS NOT NULL
),

customer_spending AS (
    SELECT
        customer_id,
        COUNT(*) AS order_count,
        SUM(total_amount) AS total_spent
    FROM eligible_orders
    GROUP BY customer_id
)

SELECT
    COUNT(*) AS total_customers,

    COUNT(cs.customer_id) AS customers_with_qualifying_orders,

    COUNT(*) FILTER (
        WHERE cs.customer_id IS NULL
    ) AS customers_without_qualifying_orders,

    COUNT(*) FILTER (
        WHERE COALESCE(cs.total_spent, 0) = 0
    ) AS customers_with_zero_recorded_spending,

    COUNT(*) AS expected_final_report_rows

FROM customers AS c
LEFT JOIN customer_spending AS cs
    ON c.customer_id = cs.customer_id;
