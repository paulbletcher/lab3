-- Phase 4, Step 4: Verify spending rules.
-- Read-only investigation.

-- Check 1: Identify missing and orphaned customer references.
SELECT
    LOWER(BTRIM(o.status)) AS normalized_status,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (
        WHERE o.customer_id IS NULL
    ) AS orders_with_null_customer_id,
    COUNT(*) FILTER (
        WHERE o.customer_id IS NOT NULL
          AND c.customer_id IS NULL
    ) AS orders_with_orphaned_customer_id,
    ROUND(
        SUM(o.total_amount) FILTER (
            WHERE o.customer_id IS NOT NULL
              AND c.customer_id IS NULL
        ), 2
    ) AS orphaned_orders_stored_total
FROM orders AS o
LEFT JOIN customers AS c
    ON o.customer_id = c.customer_id
GROUP BY LOWER(BTRIM(o.status))
ORDER BY normalized_status;


-- Check 2: Correctly identify mismatches where every item amount exists.
WITH item_quality AS (
    SELECT
        order_id,
        COUNT(*) FILTER (
            WHERE quantity IS NULL OR unit_price IS NULL
        ) AS incomplete_item_rows,
        BOOL_AND(
            quantity IS NOT NULL
            AND unit_price IS NOT NULL
        ) AS all_item_amounts_present,
        SUM(quantity * unit_price) AS calculated_item_total
    FROM order_items
    GROUP BY order_id
)
SELECT
    LOWER(BTRIM(o.status)) AS normalized_status,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (
        WHERE iq.incomplete_item_rows > 0
    ) AS orders_with_incomplete_items,
    COUNT(*) FILTER (
        WHERE iq.all_item_amounts_present IS TRUE
          AND o.total_amount IS NOT NULL
          AND o.total_amount <> iq.calculated_item_total
    ) AS complete_item_amount_mismatches
FROM orders AS o
LEFT JOIN item_quality AS iq
    ON o.order_id = iq.order_id
GROUP BY LOWER(BTRIM(o.status))
ORDER BY normalized_status;


-- Check 3: Identify future-dated orders by status.
SELECT
    LOWER(BTRIM(status)) AS normalized_status,
    COUNT(*) AS future_order_count,
    ROUND(SUM(total_amount), 2) AS future_stored_total
FROM orders
WHERE order_date::date > CURRENT_DATE
GROUP BY LOWER(BTRIM(status))
ORDER BY normalized_status;


-- Check 4: Establish the eligible completed-order reporting baseline.
SELECT
    COUNT(*) AS completed_status_orders,
    COUNT(*) FILTER (
        WHERE o.order_date < CURRENT_DATE + INTERVAL '1 day'
    ) AS orders_within_reporting_date,
    COUNT(*) FILTER (
        WHERE c.customer_id IS NOT NULL
          AND o.order_date < CURRENT_DATE + INTERVAL '1 day'
          AND o.total_amount IS NOT NULL
    ) AS eligible_customer_orders,
    ROUND(
        SUM(o.total_amount) FILTER (
            WHERE c.customer_id IS NOT NULL
              AND o.order_date < CURRENT_DATE + INTERVAL '1 day'
              AND o.total_amount IS NOT NULL
        ), 2
    ) AS eligible_stored_spending
FROM orders AS o
LEFT JOIN customers AS c
    ON o.customer_id = c.customer_id
WHERE LOWER(BTRIM(o.status)) IN ('complete', 'completed');
