-- PHASE 5: RECURSIVE LOW-STOCK CATEGORY REPORT
-- PostgreSQL 18
--
-- Threshold: stock_quantity <= 10.
-- Negative stock is included.
-- NULL stock is disclosed separately.
-- Counts include descendants and direct category counts.
-- Cycle detection terminates recursion without a fixed depth limit.

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
    FALSE AS depth_limit_reached
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
