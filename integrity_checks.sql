-- Check 1: Count orders with orphaned or NULL customer IDs.
 -- Count orphaned customer references and missing customer IDs separately.
--where orders haves customer_ids that does not exist in customers table and where orders have null customer_id

SELECT COUNT(*) FILTER (
                        WHERE o.customer_id IS NOT NULL
                            AND c.customer_id IS NULL) AS orders_with_orphaned_customer_id,
       COUNT(*) FILTER (
                        WHERE o.customer_id IS NULL) AS orders_with_null_customer_id
FROM orders AS o
LEFT JOIN customers AS c ON o.customer_id = c.customer_id;

-- Check 2: Count order items with orphaned or NULL order IDs.
--where order_items have order_ids that does not exist in orders table and where order_items have null order_id

SELECT COUNT(*) FILTER (
                        WHERE oi.order_id IS NOT NULL
                            AND o.order_id IS NULL) AS items_with_orphaned_order_id,
       COUNT(*) FILTER (
                        WHERE oi.order_id IS NULL) AS items_with_null_order_id
FROM order_items AS oi
LEFT JOIN orders AS o ON oi.order_id = o.order_id;

-- Check 3: Count order items with orphaned or NULL product IDs.
-- where order_items have product_ids that does not exist in products table and where order_items have null product_id

SELECT COUNT(*) FILTER (
                        WHERE oi.product_id IS NOT NULL
                            AND p.product_id IS NULL) AS items_with_orphaned_product_id,
       COUNT(*) FILTER (
                        WHERE oi.product_id IS NULL) AS items_with_null_product_id
FROM order_items AS oi
LEFT JOIN products AS p ON oi.product_id = p.product_id;

-- Check 4: Count inventory log entries with orphaned or NULL product IDs.
-- where inventory_log have product_ids that does not exist in products table and where inventory_log have null product_id

SELECT COUNT(*) FILTER (
                        WHERE il.product_id IS NOT NULL
                            AND p.product_id IS NULL) AS logs_with_orphaned_product_id,
       COUNT(*) FILTER (
                        WHERE il.product_id IS NULL) AS logs_with_null_product_id
FROM inventory_log AS il
LEFT JOIN products AS p ON il.product_id = p.product_id;

-- Check 5: Count products with orphaned or NULL category IDs.
-- where products have category_ids that does not exist in categories table and where products have null category_id

SELECT COUNT(*) FILTER (
                        WHERE p.category_id IS NOT NULL
                            AND c.category_id IS NULL) AS products_with_orphaned_category_id,
       COUNT(*) FILTER (
                        WHERE p.category_id IS NULL) AS products_with_null_category_id
FROM products AS p
LEFT JOIN categories AS c ON p.category_id = c.category_id;

-- Check 6: Count categories with missing parents and top-level categories.
-- Count categories whose parent_id is set but does not exist in the
-- categories table, and categories whose parent_id is NULL.

SELECT COUNT(*) FILTER (
                        WHERE child.parent_id IS NOT NULL
                            AND parent.category_id IS NULL) AS categories_with_missing_parent,
       COUNT(*) FILTER (
                        WHERE child.parent_id IS NULL) AS top_level_categories
FROM categories AS child
LEFT JOIN categories AS parent ON child.parent_id = parent.category_id;

-- Check 7: Count categories in loops and categories that lead into loops.
-- Start at each category and follow its parents. If we reach a category
-- we've already visited on that path, count the starting category and stop.
WITH RECURSIVE category_walk AS
    (SELECT category_id AS start_id,
            category_id AS current_id,
            parent_id, ARRAY[category_id] AS visited_ids,
                            false AS has_repeat
     FROM categories
     UNION ALL SELECT walk.start_id,
                      parent.category_id,
                      parent.parent_id,
                      walk.visited_ids || parent.category_id,
                      parent.category_id = ANY(walk.visited_ids)
     FROM category_walk AS walk
     JOIN categories AS parent ON walk.parent_id = parent.category_id
     WHERE NOT walk.has_repeat)
SELECT COUNT(*) FILTER (
                        WHERE has_repeat
                            AND current_id = start_id) AS categories_in_loops,
       COUNT(*) FILTER (
                        WHERE has_repeat
                            AND current_id <> start_id) AS categories_leading_into_loops
FROM category_walk;

-- Check 8: Count products with negative or NULL stock quantities.
-- Count products where stock_quantity is below zero and products where
-- stock_quantity is NULL.

SELECT COUNT(*) FILTER (
                        WHERE stock_quantity < 0) AS products_with_negative_stock,
       COUNT(*) FILTER (
                        WHERE stock_quantity IS NULL) AS products_with_null_stock
FROM products;

-- Check 9: Count order items with negative, zero, or NULL quantities.
-- Count order items where quantity is below zero, where quantity is zero,
-- and where quantity is NULL.

SELECT COUNT(*) FILTER (
                        WHERE quantity < 0) AS items_with_negative_quantity,
       COUNT(*) FILTER (
                        WHERE quantity = 0) AS items_with_zero_quantity,
       COUNT(*) FILTER (
                        WHERE quantity IS NULL) AS items_with_null_quantity
FROM order_items;

-- Check 10: Count order items with negative, zero, or NULL unit prices.
-- Count order items where unit_price is below zero, where unit_price is zero,
-- and where unit_price is NULL.

SELECT COUNT(*) FILTER (
                        WHERE unit_price < 0) AS items_with_negative_unit_price,
       COUNT(*) FILTER (
                        WHERE unit_price = 0) AS items_with_zero_unit_price,
       COUNT(*) FILTER (
                        WHERE unit_price IS NULL) AS items_with_null_unit_price
FROM order_items;

-- Check 11: Compare stored order totals with the sum of the line items.
-- Count orders with no items, orders with a missing line amount,
-- and orders with a NULL stored total. Count differences only when
-- the stored total and all line amounts are available.
WITH item_totals AS
    (SELECT order_id,
            SUM(quantity * unit_price) AS calculated_total,
            COUNT(*) FILTER (
                             WHERE quantity IS NULL
                                 OR unit_price IS NULL) AS incomplete_lines
     FROM order_items
     GROUP BY order_id)
SELECT COUNT(*) FILTER (
                        WHERE it.order_id IS NULL) AS orders_without_items,
       COUNT(*) FILTER (
                        WHERE it.incomplete_lines > 0) AS orders_with_incomplete_lines,
       COUNT(*) FILTER (
                        WHERE o.total_amount IS NULL) AS orders_with_null_total,
       COUNT(*) FILTER (
                        WHERE it.incomplete_lines = 0
                            AND o.total_amount <> it.calculated_total) AS orders_with_total_mismatch
FROM orders AS o
LEFT JOIN item_totals AS it ON o.order_id = it.order_id;

-- Check 12: Count orders for each status.
-- Group orders by the exact status stored in the orders table and
-- show how many orders have each value, including NULL and blank values.

SELECT QUOTE_NULLABLE(status) AS recorded_status,
       COUNT(*) AS order_count
FROM orders
GROUP BY status
ORDER BY order_count DESC,
         recorded_status;

-- Check 13: Count orders with missing dates and show the order date range.
-- Count orders where order_date is NULL, then find the earliest and
-- latest recorded order dates.

SELECT COUNT(*) FILTER (
                        WHERE order_date IS NULL) AS orders_with_null_date,
       MIN(order_date)::date AS earliest_order_date,
       MAX(order_date)::date AS latest_order_date
FROM orders;

-- Check 14: Count inventory log entries with NULL or zero stock changes.
-- Count entries where change_qty is NULL and entries where change_qty is zero.

SELECT COUNT(*) FILTER (
                        WHERE change_qty IS NULL) AS logs_with_null_change_qty,
       COUNT(*) FILTER (
                        WHERE change_qty = 0) AS logs_with_zero_change_qty
FROM inventory_log;

-- Check 15: Count negative, zero, and positive stock changes by reason.
-- Group entries by the reason recorded in the inventory log and count
-- how many removed stock, recorded zero change, or added stock.

SELECT QUOTE_NULLABLE(reason) AS recorded_reason,
       COUNT(*) FILTER (
                        WHERE change_qty < 0) AS stock_decreases,
       COUNT(*) FILTER (
                        WHERE change_qty = 0) AS zero_changes,
       COUNT(*) FILTER (
                        WHERE change_qty > 0) AS stock_increases,
       COUNT(*) AS log_count
FROM inventory_log
GROUP BY reason
ORDER BY log_count DESC,
         recorded_reason;

-- Check 16: Count products with negative, zero, or NULL prices.
-- Count products where price is below zero, where price is zero,
-- and where price is NULL.

SELECT COUNT(*) FILTER (
                        WHERE price < 0) AS products_with_negative_price,
       COUNT(*) FILTER (
                        WHERE price = 0) AS products_with_zero_price,
       COUNT(*) FILTER (
                        WHERE price IS NULL) AS products_with_null_price
FROM products;

-- Check 17: Count email addresses used by more than one customer record.
-- Ignore missing and blank emails. Compare the remaining addresses
-- in lowercase after removing leading and trailing spaces.
WITH repeated_emails AS
    (SELECT LOWER(TRIM(email)) AS normalized_email,
            COUNT(*) AS customer_count
     FROM customers
     WHERE email IS NOT NULL
         AND TRIM(email) <> ''
     GROUP BY normalized_email
     HAVING COUNT(*) > 1)
SELECT COUNT(*) AS duplicate_email_groups,
       COALESCE(SUM(customer_count), 0) AS customer_rows_in_duplicate_email_groups
FROM repeated_emails;

-- Check 18: Count completed orders that point to missing customers.
-- Keep orders with a customer ID that does not exist in the customers
-- table and a status of complete or completed. Add up their stored totals.

SELECT COUNT(*) AS completed_orders_with_missing_customers,
       COALESCE(SUM(o.total_amount), 0) AS stored_total_for_those_orders
FROM orders AS o
LEFT JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.customer_id IS NOT NULL
    AND c.customer_id IS NULL
    AND LOWER(TRIM(o.status)) IN ('complete',
                                  'completed');

-- Check 19: Measure order total differences for completed orders.
-- Add up quantity times unit_price for orders with complete line amounts.
-- Compare that sum with the stored total and add up the differences.
WITH item_totals AS
    (SELECT order_id,
            SUM(quantity * unit_price) AS calculated_total
     FROM order_items
     GROUP BY order_id
     HAVING COUNT(*) = COUNT(quantity * unit_price)),
     completed_differences AS
    (SELECT o.total_amount - it.calculated_total AS total_difference
     FROM orders AS o
     JOIN item_totals AS it ON o.order_id = it.order_id
     WHERE LOWER(TRIM(o.status)) IN ('complete',
                                     'completed')
         AND o.total_amount IS NOT NULL
         AND o.total_amount <> it.calculated_total)
SELECT COUNT(*) AS completed_orders_with_total_mismatch,
       COALESCE(SUM(total_difference), 0) AS net_difference,
       COALESCE(SUM(ABS(total_difference)), 0) AS total_absolute_difference
FROM completed_differences;

-- Check 20: Count completed orders with missing line amounts.
-- Find completed orders where at least one item has a NULL quantity
-- or unit_price, then add up the stored totals for those orders.

SELECT COUNT(*) AS completed_orders_with_incomplete_lines,
       COALESCE(SUM(o.total_amount), 0) AS stored_total_for_those_orders
FROM orders AS o
WHERE LOWER(TRIM(o.status)) IN ('complete',
                                'completed')
    AND EXISTS
        (SELECT 1
         FROM order_items AS oi
         WHERE oi.order_id = o.order_id
             AND (oi.quantity IS NULL
                  OR oi.unit_price IS NULL));