-- Investigation 3: Preflight integrity checks.
-- Verify historical row counts after concurrency testing.

SELECT 'products' AS table_name, COUNT(*) AS row_count
FROM products

UNION ALL

SELECT 'orders', COUNT(*) FROM orders

UNION ALL

SELECT 'order_items', COUNT(*) FROM order_items

UNION ALL

SELECT 'inventory_log', COUNT(*) FROM inventory_log;


-- Check for remaining official test fixtures.

SELECT COUNT(*) AS remaining_fixtures
FROM products
WHERE product_name LIKE 'RACE TEST FIXTURE%';


-- Check whether the next flash-sale fixture ID
-- is referenced by existing historical records.

WITH fixture AS (
    SELECT MAX(product_id) + 1100 AS product_id
    FROM products
)
SELECT
    f.product_id AS next_fixture_id,
    (
        SELECT COUNT(*)
        FROM order_items AS oi
        WHERE oi.product_id = f.product_id
    ) AS existing_item_references,
    (
        SELECT COUNT(*)
        FROM inventory_log AS il
        WHERE il.product_id = f.product_id
    ) AS existing_log_references
FROM fixture AS f;