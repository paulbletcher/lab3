
-- Phase 4, Step 9: Calculate customer spending and order counts.
-- Read-only prototype.
--
-- Expected grain: one row per customer.
-- Customers without qualifying orders must remain in the report.

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

customer_totals AS (
    SELECT
        customer_id,
        COUNT(*) AS order_count,
        SUM(total_amount) AS total_spent
    FROM eligible_orders
    GROUP BY customer_id
),

customer_report AS (
    SELECT
        c.customer_id,
        c.full_name,
        COALESCE(ct.order_count, 0) AS order_count,
        COALESCE(ct.total_spent, 0::numeric) AS total_spent
    FROM customers AS c
    LEFT JOIN customer_totals AS ct
        ON c.customer_id = ct.customer_id
)

-- Check 1: Validate the complete customer report.
SELECT
    COUNT(*) AS total_customers,

    COUNT(*) FILTER (
        WHERE order_count > 0
    ) AS customers_with_orders,

    COUNT(*) FILTER (
        WHERE order_count = 0
    ) AS customers_without_orders,

    SUM(order_count) AS total_eligible_orders,

    ROUND(SUM(total_spent), 2) AS total_customer_spending,

    COUNT(*) FILTER (
        WHERE total_spent = 0
    ) AS customers_with_zero_spending

FROM customer_report;


-- Check 2: Preview the ten highest-spending customers.
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

customer_totals AS (
    SELECT
        customer_id,
        COUNT(*) AS order_count,
        SUM(total_amount) AS total_spent
    FROM eligible_orders
    GROUP BY customer_id
)

SELECT
    c.customer_id,
    c.full_name,
    COALESCE(ct.order_count, 0) AS order_count,
    COALESCE(ct.total_spent, 0::numeric) AS total_spent
FROM customers AS c
LEFT JOIN customer_totals AS ct
    ON c.customer_id = ct.customer_id
ORDER BY total_spent DESC, c.customer_id
LIMIT 10;
