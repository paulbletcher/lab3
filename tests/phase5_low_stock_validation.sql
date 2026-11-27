-- Retained original Phase 5 exploratory validations; fixtures roll back.
-- VALIDATION 1: Actual category report.
SELECT *
FROM public.report_low_stock_by_category
ORDER BY descendant_low_stock_products DESC, category_id
LIMIT 20;


-- VALIDATION 2: Actual hierarchy and depth.
SELECT
    COUNT(DISTINCT category_id) AS reachable_categories,
    MAX(depth) AS maximum_depth,
    COUNT(*) FILTER (
        WHERE depth_limit_reached
    ) AS truncated_categories
FROM public.report_category_hierarchy
WHERE NOT is_cycle;


-- VALIDATION 3: Actual cycle detection.
SELECT
    COUNT(DISTINCT start_category_id) AS cycle_start_categories
FROM public.report_category_cycles;


-- VALIDATION 4: Exception summary.
SELECT
    exception_type,
    COUNT(*) AS exception_count
FROM public.report_category_exceptions
GROUP BY exception_type
ORDER BY exception_type;


-- VALIDATION 5: Top-level reconciliation.
WITH top_level_total AS (
    SELECT
        COALESCE(SUM(descendant_low_stock_products), 0)
            AS low_stock_count
    FROM public.report_low_stock_by_category
    WHERE parent_id IS NULL
),
eligible_total AS (
    SELECT
        COUNT(DISTINCT p.product_id) AS low_stock_count
    FROM products AS p
    JOIN public.report_category_hierarchy AS h
        ON h.category_id = p.category_id
    WHERE NOT h.is_cycle
      AND p.stock_quantity <= 10
)
SELECT
    t.low_stock_count AS top_level_rollup,
    e.low_stock_count AS eligible_product_count,
    t.low_stock_count = e.low_stock_count AS reconciles
FROM top_level_total AS t
CROSS JOIN eligible_total AS e;


-- SYNTHETIC TESTS: Create temporary hierarchy and product fixtures.
-- All fixture writes are rolled back at the end.

BEGIN;

INSERT INTO categories (
    category_id, category_name, parent_id
)
VALUES
    (-900000000, 'TEST ROOT', NULL),
    (-900000001, 'TEST CHILD', -900000000),
    (-900000002, 'TEST GRANDCHILD', -900000001),
    (-900000003, 'TEST DEEP LEAF', -900000002),
    (-900000004, 'TEST CYCLE A', -900000005),
    (-900000005, 'TEST CYCLE B', -900000004),
    (-900000006, 'TEST ORPHAN', -900000099);

INSERT INTO products (
    product_id, product_name, category_id,
    price, stock_quantity, created_at
)
VALUES
    (-910000000, 'TEST THRESHOLD', -900000003, 10, 10, NOW()),
    (-910000001, 'TEST NEGATIVE STOCK', -900000003, 10, -2, NOW()),
    (-910000002, 'TEST UNCATEGORIZED', NULL, 10, 1, NOW()),
    (-910000003, 'TEST ORPHAN PRODUCT', -900000099, 10, 1, NOW()),
    (-910000004, 'TEST NULL STOCK', -900000003, 10, NULL, NOW());


-- TEST 1: Four-level hierarchy.
SELECT
    category_id,
    depth
FROM public.report_category_hierarchy
WHERE category_id = -900000003;


-- TEST 2: Threshold and negative stock.
SELECT
    category_id,
    direct_low_stock_products,
    descendant_low_stock_products,
    descendant_products_with_null_stock
FROM public.report_low_stock_by_category
WHERE category_id IN (-900000000, -900000003)
ORDER BY category_id;


-- TEST 3: Cycle detection.
SELECT
    COUNT(DISTINCT start_category_id) AS detected_cycle_members
FROM public.report_category_cycles
WHERE start_category_id IN (-900000004, -900000005);


-- TEST 4: Orphan, uncategorized and NULL stock exceptions.
SELECT
    exception_type,
    COUNT(*) AS detected
FROM public.report_category_exceptions
WHERE category_id IN (-900000006, -900000099)
   OR product_id BETWEEN -910000004 AND -910000000
GROUP BY exception_type
ORDER BY exception_type;


-- TEST 5: No duplicate ancestor/category paths.
SELECT
    COUNT(*) AS duplicate_paths
FROM (
    SELECT
        root_category_id,
        category_id
    FROM public.report_category_hierarchy
    GROUP BY root_category_id, category_id
    HAVING COUNT(*) > 1
) AS duplicates;


-- Roll back all synthetic data.
ROLLBACK;

