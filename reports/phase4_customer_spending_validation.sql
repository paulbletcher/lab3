-- Phase 4: Validate customer spending reporting views.
-- The three reporting views have already been created.

-- Check 1: Validate all customers, orders and monthly entries.
WITH month_counts AS (
    SELECT
        r.customer_id,
        COUNT(k.month_key) AS month_count
    FROM public.report_customer_spending AS r
    LEFT JOIN LATERAL jsonb_object_keys(
        r.monthly_spend_trailing_12_months
    ) AS k(month_key) ON TRUE
    GROUP BY r.customer_id
)
SELECT
    COUNT(*) AS total_customers,
    COUNT(*) FILTER (
        WHERE r.order_count > 0
    ) AS customers_with_orders,
    COUNT(*) FILTER (
        WHERE r.order_count = 0
    ) AS customers_without_orders,
    SUM(r.order_count) AS total_orders,
    ROUND(SUM(r.total_spent), 2) AS total_spending,
    COUNT(*) FILTER (
        WHERE mc.month_count = 12
    ) AS customers_with_12_months
FROM public.report_customer_spending AS r
JOIN month_counts AS mc
    ON mc.customer_id = r.customer_id;


-- Check 2: Top 10 customers.
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


-- Check 3: Verify exactly 100 top-100 positions.
SELECT
    COUNT(*) AS top_100_customers
FROM public.report_customer_spending
WHERE is_top_100;


-- Check 4: Inspect running customer spending totals.
SELECT *
FROM public.report_customer_order_running_totals
ORDER BY customer_id, order_date, order_id
LIMIT 10;


-- Check 5: Inspect monthly spending for one customer.
SELECT
    customer_id,
    full_name,
    monthly_spend_trailing_12_months
FROM public.report_customer_spending
WHERE order_count > 0
ORDER BY total_spent DESC, customer_id
LIMIT 1;
