\set ON_ERROR_STOP on
\ir test_support.sql
BEGIN;
SELECT pg_temp.check(COUNT(*)=91 AND MAX(depth)=4
    AND COUNT(*) FILTER (WHERE depth_limit_reached)=0,'actual hierarchy: 91 categories, depth four')
FROM public.report_category_hierarchy WHERE NOT is_cycle;
SELECT pg_temp.check(COUNT(DISTINCT start_category_id)=2,'actual category cycle members')
FROM public.report_category_cycles;
SELECT pg_temp.check(SUM(descendant_low_stock_products)=1931,'actual root total: 1931')
FROM public.report_low_stock_by_category WHERE parent_id IS NULL;
SELECT pg_temp.check(COUNT(*) FILTER (WHERE exception_type='category_missing_parent')=1
    AND COUNT(*) FILTER (WHERE exception_type='category_not_reachable_from_root')=3
    AND COUNT(*) FILTER (WHERE exception_type='uncategorized_product')=37,
    'actual orphan, unreachable and uncategorized exceptions') FROM public.report_category_exceptions;
INSERT INTO public.categories(category_id,category_name,parent_id)
SELECT -870000000+n, 'SYNTHETIC DEEP CATEGORY',
       CASE WHEN n=1 THEN NULL ELSE -870000000+n-1 END
FROM generate_series(1,35) n;
INSERT INTO public.categories VALUES
    (-870000100,'SYNTHETIC CYCLE A',-870000101),
    (-870000101,'SYNTHETIC CYCLE B',-870000100),
    (-870000102,'SYNTHETIC ORPHAN',-870000199),
    (-870000103,'SYNTHETIC SELF LOOP',-870000103);
INSERT INTO public.products(product_id,product_name,category_id,price,stock_quantity) VALUES
    (-871000000,'SYNTHETIC BOUNDARY',-869999965,10,10),
    (-871000001,'SYNTHETIC ABOVE',-869999965,10,11),
    (-871000002,'SYNTHETIC NEGATIVE',-869999965,10,-2),
    (-871000003,'SYNTHETIC NULL',-869999965,10,NULL),
    (-871000004,'SYNTHETIC UNCATEGORIZED',NULL,10,1),
    (-871000005,'SYNTHETIC ORPHAN PRODUCT',-870000199,10,1);
SELECT pg_temp.check(depth=35 AND NOT depth_limit_reached,'35-level hierarchy is fully traversed')
FROM public.report_category_hierarchy WHERE category_id=-869999965;
SELECT pg_temp.check(descendant_low_stock_products=2 AND descendant_products_with_null_stock=1,
    'deep root: threshold inclusive, negative included, NULL disclosed')
FROM public.report_low_stock_by_category WHERE category_id=-869999999;
SELECT pg_temp.check(direct_low_stock_products=2,'leaf direct count excludes stock above threshold')
FROM public.report_low_stock_by_category WHERE category_id=-869999965;
SELECT pg_temp.check(COUNT(DISTINCT start_category_id)=3,'synthetic two-member and self cycles terminate')
FROM public.report_category_cycles WHERE start_category_id IN (-870000100,-870000101,-870000103);
SELECT pg_temp.check(NOT EXISTS (
    SELECT FROM public.report_category_hierarchy GROUP BY root_category_id,category_id HAVING COUNT(*)>1),
    'no duplicate hierarchy paths');
SELECT pg_temp.check(COUNT(*) FILTER (WHERE exception_type='orphaned_product_category')=1
    AND COUNT(*) FILTER (WHERE exception_type='uncategorized_product')=1
    AND COUNT(*) FILTER (WHERE exception_type='null_stock_quantity')=1,
    'synthetic product exceptions are explicit')
FROM public.report_category_exceptions WHERE product_id BETWEEN -871000005 AND -871000000;
\ir final_assertions.sql
ROLLBACK;
