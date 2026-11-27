-- PHASE 5: RECURSIVE LOW-STOCK CATEGORY REPORT
-- PostgreSQL 18
--
-- Threshold: stock_quantity <= 10.
-- Negative stock is included.
-- NULL stock is disclosed separately.
-- Counts include descendants and direct category counts.
-- Maximum hierarchy traversal depth: 20.

-- VIEW 1: Traverse valid category trees from their roots.
CREATE OR REPLACE VIEW public.report_category_hierarchy AS
WITH RECURSIVE category_tree (
    root_category_id,
    category_id,
    category_name,
    parent_id,
    depth
) AS (
    SELECT
        c.category_id,
        c.category_id,
        c.category_name,
        c.parent_id,
        1
    FROM categories AS c
    WHERE c.parent_id IS NULL

    UNION ALL

    SELECT
        t.root_category_id,
        c.category_id,
        c.category_name,
        c.parent_id,
        t.depth + 1
    FROM categories AS c
    JOIN category_tree AS t
        ON c.parent_id = t.category_id
    WHERE t.depth < 20
)
CYCLE category_id SET is_cycle USING cycle_path

SELECT
    root_category_id,
    category_id,
    category_name,
    parent_id,
    depth,
    is_cycle,
    cycle_path::text AS cycle_path,
    (
        depth = 20
        AND EXISTS (
            SELECT 1
            FROM categories AS child
            WHERE child.parent_id = category_tree.category_id
        )
    ) AS depth_limit_reached
FROM category_tree;


-- VIEW 2: Detect cycles, including cycles not connected to a root.
CREATE OR REPLACE VIEW public.report_category_cycles AS
WITH RECURSIVE walks (
    start_category_id,
    current_category_id,
    depth
) AS (
    SELECT
        category_id,
        category_id,
        0
    FROM categories

    UNION ALL

    SELECT
        w.start_category_id,
        c.category_id,
        w.depth + 1
    FROM walks AS w
    JOIN categories AS c
        ON c.parent_id = w.current_category_id
    WHERE w.depth < 20
)
CYCLE current_category_id SET is_cycle USING cycle_path

SELECT DISTINCT
    start_category_id,
    current_category_id AS repeated_category_id,
    depth,
    cycle_path::text AS cycle_path
FROM walks
WHERE is_cycle;


-- VIEW 3: Count low-stock products directly and throughout
-- each valid category's descendant subtree.
CREATE OR REPLACE VIEW public.report_low_stock_by_category AS

WITH RECURSIVE valid_categories AS (
    SELECT DISTINCT category_id
    FROM public.report_category_hierarchy
    WHERE NOT is_cycle
),

subtree (
    ancestor_category_id,
    descendant_category_id,
    depth
) AS (
    SELECT
        category_id,
        category_id,
        0
    FROM valid_categories

    UNION ALL

    SELECT
        s.ancestor_category_id,
        c.category_id,
        s.depth + 1
    FROM subtree AS s
    JOIN categories AS c
        ON c.parent_id = s.descendant_category_id
    JOIN valid_categories AS vc
        ON vc.category_id = c.category_id
    WHERE s.depth < 20
)
CYCLE descendant_category_id SET is_cycle USING cycle_path,

counts AS (
    SELECT
        s.ancestor_category_id,

        COUNT(DISTINCT p.product_id) FILTER (
            WHERE p.stock_quantity <= 10
        ) AS low_stock_products_in_subtree,

        COUNT(DISTINCT p.product_id) FILTER (
            WHERE s.depth = 0
              AND p.stock_quantity <= 10
        ) AS low_stock_products_direct,

        COUNT(DISTINCT p.product_id) FILTER (
            WHERE p.stock_quantity IS NULL
        ) AS null_stock_products_in_subtree

    FROM subtree AS s
    JOIN products AS p
        ON p.category_id = s.descendant_category_id
    WHERE NOT s.is_cycle
    GROUP BY s.ancestor_category_id
)

SELECT
    c.category_id,
    c.category_name,
    c.parent_id,
    COALESCE(ct.low_stock_products_direct, 0)
        AS direct_low_stock_products,
    COALESCE(ct.low_stock_products_in_subtree, 0)
        AS descendant_low_stock_products,
    COALESCE(ct.null_stock_products_in_subtree, 0)
        AS descendant_products_with_null_stock

FROM categories AS c
LEFT JOIN counts AS ct
    ON ct.ancestor_category_id = c.category_id;


-- VIEW 4: Explicit data-quality exceptions.
CREATE OR REPLACE VIEW public.report_category_exceptions AS

SELECT
    'uncategorized_product'::text AS exception_type,
    NULL::integer AS category_id,
    p.product_id,
    'Product has no category assignment'::text AS details
FROM products AS p
WHERE p.category_id IS NULL

UNION ALL

SELECT
    'orphaned_product_category',
    p.category_id,
    p.product_id,
    'Product references a category that does not exist'
FROM products AS p
WHERE p.category_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM categories AS c
      WHERE c.category_id = p.category_id
  )

UNION ALL

SELECT
    'null_stock_quantity',
    p.category_id,
    p.product_id,
    'Product stock quantity is NULL'
FROM products AS p
WHERE p.stock_quantity IS NULL

UNION ALL

SELECT
    'category_missing_parent',
    c.category_id,
    NULL::integer,
    'Category references a parent that does not exist'
FROM categories AS c
WHERE c.parent_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM categories AS parent
      WHERE parent.category_id = c.parent_id
  )

UNION ALL

SELECT
    'category_not_reachable_from_root',
    c.category_id,
    NULL::integer,
    'Category is not reachable from a valid root'
FROM categories AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM public.report_category_hierarchy AS h
    WHERE h.category_id = c.category_id
      AND NOT h.is_cycle
)

UNION ALL

SELECT
    'depth_limit_reached',
    h.category_id,
    NULL::integer,
    'Further descendants exist beyond the depth limit'
FROM public.report_category_hierarchy AS h
WHERE h.depth_limit_reached;


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

