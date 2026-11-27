-- Phase 4, Step 3: Profile order statuses and reporting dates.
-- Read-only investigation.

-- Check 1: Database date and order date range.
SELECT
    CURRENT_DATE AS database_date,
    MIN(order_date) AS earliest_order,
    MAX(order_date) AS latest_order,
    COUNT(*) FILTER (
        WHERE order_date::date > CURRENT_DATE
    ) AS future_dated_orders,
    COUNT(*) AS total_orders
FROM orders;


-- Check 2: Examine original status values and normalized status groups.
SELECT
    LOWER(BTRIM(status)) AS normalized_status,
    ARRAY_AGG(DISTINCT status ORDER BY status) AS original_variants,
    COUNT(*) AS order_count,
    COUNT(*) FILTER (
        WHERE customer_id IS NULL
    ) AS orders_without_customer,
    COUNT(*) FILTER (
        WHERE total_amount IS NULL
    ) AS orders_without_total,
    ROUND(SUM(total_amount), 2) AS stored_order_total
FROM orders
GROUP BY LOWER(BTRIM(status))
ORDER BY normalized_status;


-- Check 3: Examine order distribution by year and month.
SELECT
    DATE_TRUNC('month', order_date)::date AS order_month,
    COUNT(*) AS order_count,
    ROUND(SUM(total_amount), 2) AS stored_order_total
FROM orders
GROUP BY DATE_TRUNC('month', order_date)
ORDER BY order_month;


-- Check 4: Examine completed orders with incomplete or complete
-- item amounts, grouped by normalized status.
WITH item_quality AS (
    SELECT
        order_id,
        COUNT(*) AS item_rows,
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
        WHERE iq.order_id IS NULL
    ) AS orders_without_items,
    COUNT(*) FILTER (
        WHERE iq.incomplete_item_rows > 0
    ) AS orders_with_incomplete_items,
    COUNT(*) FILTER (
        WHERE iq.order_id IS NOT NULL
          AND iq.all_item_amounts_present
    ) AS orders_with_complete_item_amounts,
    COUNT(*) FILTER (
        WHERE iq.order_id IS NOT NULL
          AND iq.all_item_amounts_present
          AND o.total_amount <> iq.calculated_item_total
    ) AS orders_with_total_mismatch
FROM orders AS o
LEFT JOIN item_quality AS iq
    ON o.order_id = iq.order_id
GROUP BY LOWER(BTRIM(o.status))
ORDER BY normalized_status;
